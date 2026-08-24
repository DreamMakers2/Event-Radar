from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from event_radar.config import Settings


ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class BillingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fx_cache: dict[str, Any] | None = None
        self._credit_cache: dict[str, Any] | None = None
        self._credit_cache_at = 0.0
        self._org_costs_cache: dict[str, Any] | None = None
        self._org_costs_cache_at = 0.0
        self._openai_key_scope_cache: dict[str, Any] | None = None
        self._openai_key_scope_cache_at = 0.0
        self._x_usage_cache: dict[str, Any] | None = None
        self._x_usage_cache_at = 0.0

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float:
        input_tokens = max(input_tokens - cached_input_tokens, 0)
        total = (
            (input_tokens / 1_000_000) * self.settings.openai_input_cost_per_million_usd
            + (cached_input_tokens / 1_000_000) * self.settings.openai_cached_input_cost_per_million_usd
            + (output_tokens / 1_000_000) * self.settings.openai_output_cost_per_million_usd
        )
        return round(total, 8)

    async def eur_per_usd(self) -> tuple[float, str]:
        now = time.time()
        if self._fx_cache and now - self._fx_cache["fetched_at"] < 60 * 60 * 12:
            return self._fx_cache["eur_per_usd"], self._fx_cache["reference_date"]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(ECB_URL)
                response.raise_for_status()
            root = ET.fromstring(response.text)
            ns = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
            date_node = root.find(".//ecb:Cube[@time]", ns)
            usd_node = root.find(".//ecb:Cube[@currency='USD']", ns)
            if date_node is None or usd_node is None:
                raise ValueError("missing_ecb_usd_rate")
            usd_per_eur = float(usd_node.attrib["rate"])
            eur_per_usd = round(1.0 / usd_per_eur, 6)
            reference_date = date_node.attrib["time"]
            self._fx_cache = {"eur_per_usd": eur_per_usd, "reference_date": reference_date, "fetched_at": now}
            return eur_per_usd, reference_date
        except Exception:
            return self.settings.eur_per_usd_default, "fallback"

    async def fetch_available_credit(self) -> dict[str, Any]:
        now = time.time()
        if self._credit_cache and now - self._credit_cache_at < 60 * 15:
            return self._credit_cache
        if not self.settings.openai_admin_key:
            payload = {"status": "unavailable", "reason": "missing_openai_admin_key"}
            self._credit_cache = payload
            self._credit_cache_at = now
            return payload
        headers = {"Authorization": f"Bearer {self.settings.openai_admin_key.get_secret_value()}"}
        endpoints = [
            "https://api.openai.com/dashboard/billing/credit_grants",
            "https://api.openai.com/v1/dashboard/billing/credit_grants",
        ]
        async with httpx.AsyncClient(timeout=10.0) as client:
            for endpoint in endpoints:
                try:
                    response = await client.get(endpoint, headers=headers)
                    if response.status_code == 403:
                        payload = {"status": "unavailable", "reason": "browser_session_required"}
                        self._credit_cache = payload
                        self._credit_cache_at = now
                        return payload
                    response.raise_for_status()
                    data = response.json()
                    total_available = (
                        data.get("total_available")
                        or (data.get("grants") or {}).get("total_available")
                        or (data.get("credit_summary") or {}).get("total_available")
                        or 0
                    )
                    payload = {
                        "status": "ok",
                        "available_credit_usd": round(float(total_available), 2),
                        "raw": data,
                    }
                    self._credit_cache = payload
                    self._credit_cache_at = now
                    return payload
                except httpx.HTTPError:
                    continue
        payload = {"status": "unavailable", "reason": "endpoint_failed"}
        self._credit_cache = payload
        self._credit_cache_at = now
        return payload

    async def fetch_organization_costs(self, *, days: int = 31, project_ids: list[str] | None = None) -> dict[str, Any]:
        now = time.time()
        cache_key_project_ids = project_ids or []
        if (
            self._org_costs_cache
            and now - self._org_costs_cache_at < 60 * 15
            and self._org_costs_cache.get("days") == days
            and self._org_costs_cache.get("project_ids") == cache_key_project_ids
        ):
            return self._org_costs_cache
        if not self.settings.openai_admin_key:
            payload = {"status": "unavailable", "reason": "missing_openai_admin_key", "days": days, "project_ids": cache_key_project_ids}
            self._org_costs_cache = payload
            self._org_costs_cache_at = now
            return payload
        start = int(now) - (60 * 60 * 24 * days)
        headers = {"Authorization": f"Bearer {self.settings.openai_admin_key.get_secret_value()}"}
        params: list[tuple[str, str]] = [
            ("start_time", str(start)),
            ("limit", str(days)),
        ]
        if project_ids:
            params.extend(("project_ids[]", project_id) for project_id in project_ids)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get("https://api.openai.com/v1/organization/costs", headers=headers, params=params)
            if response.status_code == 403:
                payload = {
                    "status": "unavailable",
                    "reason": "forbidden",
                    "days": days,
                    "project_ids": cache_key_project_ids,
                }
                self._org_costs_cache = payload
                self._org_costs_cache_at = now
                return payload
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            payload = {
                "status": "unavailable",
                "reason": f"http_{exc.response.status_code}",
                "days": days,
                "project_ids": cache_key_project_ids,
            }
            self._org_costs_cache = payload
            self._org_costs_cache_at = now
            return payload
        except (httpx.HTTPError, ValueError):
            payload = {
                "status": "unavailable",
                "reason": "request_failed",
                "days": days,
                "project_ids": cache_key_project_ids,
            }
            self._org_costs_cache = payload
            self._org_costs_cache_at = now
            return payload
        buckets = raw.get("data", [])
        daily_costs: list[dict[str, Any]] = []
        for bucket in buckets:
            bucket_cost = self._extract_bucket_cost_usd(bucket)
            daily_costs.append(
                {
                    "start_time": bucket.get("start_time"),
                    "end_time": bucket.get("end_time"),
                    "cost_usd": bucket_cost,
                }
            )
        payload = {
            "status": "ok",
            "days": days,
            "project_ids": cache_key_project_ids,
            "daily_costs": daily_costs,
            "billed_last_7d_usd": round(sum(item["cost_usd"] for item in daily_costs[-7:]), 4),
            "billed_last_30d_usd": round(sum(item["cost_usd"] for item in daily_costs[-30:]), 4),
            "billed_total_window_usd": round(sum(item["cost_usd"] for item in daily_costs), 4),
            "raw": raw,
        }
        self._org_costs_cache = payload
        self._org_costs_cache_at = now
        return payload

    async def fetch_x_post_usage(self, *, days: int = 30) -> dict[str, Any]:
        now = time.time()
        if (
            self._x_usage_cache
            and now - self._x_usage_cache_at < 60 * 15
            and self._x_usage_cache.get("days") == days
        ):
            return self._x_usage_cache
        if not self.settings.x_bearer_token:
            payload = {"status": "unavailable", "reason": "missing_x_bearer_token", "days": days}
            self._x_usage_cache = payload
            self._x_usage_cache_at = now
            return payload
        headers = {"Authorization": f"Bearer {self.settings.x_bearer_token.get_secret_value()}"}
        params = {
            "days": str(days),
            "usage.fields": "project_usage,daily_project_usage,project_cap,cap_reset_day,project_id",
        }
        try:
            async with httpx.AsyncClient(base_url=self.settings.x_api_base_url, timeout=10.0) as client:
                response = await client.get("/2/usage/tweets", headers=headers, params=params)
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            payload = {
                "status": "unavailable",
                "reason": f"http_{exc.response.status_code}",
                "days": days,
            }
            self._x_usage_cache = payload
            self._x_usage_cache_at = now
            return payload
        except (httpx.HTTPError, ValueError):
            payload = {"status": "unavailable", "reason": "request_failed", "days": days}
            self._x_usage_cache = payload
            self._x_usage_cache_at = now
            return payload

        data = raw.get("data") or {}
        daily_usage = self._normalize_x_daily_usage(data.get("daily_project_usage"))
        payload = {
            "status": "ok",
            "days": days,
            "project_id": data.get("project_id") or (data.get("daily_project_usage") or {}).get("project_id"),
            "project_cap": self._parse_int(data.get("project_cap")),
            "project_usage": self._parse_int(data.get("project_usage")),
            "cap_reset_day": self._parse_int(data.get("cap_reset_day")),
            "daily_usage": daily_usage,
            "consumed_last_7d": sum(item["consumed"] for item in daily_usage[-7:]),
            "consumed_last_30d": sum(item["consumed"] for item in daily_usage[-30:]),
            "raw": raw,
        }
        self._x_usage_cache = payload
        self._x_usage_cache_at = now
        return payload

    async def resolve_openai_api_key_scope(self) -> dict[str, Any]:
        now = time.time()
        if self._openai_key_scope_cache and now - self._openai_key_scope_cache_at < 60 * 15:
            return self._openai_key_scope_cache
        if not self.settings.openai_admin_key:
            payload = {"status": "unavailable", "reason": "missing_openai_admin_key"}
            self._openai_key_scope_cache = payload
            self._openai_key_scope_cache_at = now
            return payload
        headers = {"Authorization": f"Bearer {self.settings.openai_admin_key.get_secret_value()}"}
        async with httpx.AsyncClient(base_url="https://api.openai.com/v1", timeout=20.0, headers=headers) as client:
            try:
                projects_response = await client.get("/organization/projects", params={"limit": "100"})
                projects_response.raise_for_status()
            except httpx.HTTPError:
                payload = {"status": "unavailable", "reason": "project_lookup_failed"}
                self._openai_key_scope_cache = payload
                self._openai_key_scope_cache_at = now
                return payload
            projects = (projects_response.json() or {}).get("data") or []
            target_project_name = self.settings.openai_usage_project_name.strip()
            target_name = self.settings.openai_usage_api_key_name.strip()
            candidate_projects = projects
            if target_project_name:
                exact_project_matches = [
                    project for project in projects if (project.get("name") or "").strip() == target_project_name
                ]
                if not exact_project_matches:
                    payload = {
                        "status": "unavailable",
                        "reason": "target_project_not_found",
                        "project_name": target_project_name,
                        "api_key_name": target_name,
                    }
                    self._openai_key_scope_cache = payload
                    self._openai_key_scope_cache_at = now
                    return payload
                candidate_projects = exact_project_matches
            for project in candidate_projects:
                project_id = project.get("id")
                if not project_id:
                    continue
                try:
                    keys_response = await client.get(f"/organization/projects/{project_id}/api_keys", params={"limit": "100"})
                    keys_response.raise_for_status()
                except httpx.HTTPError:
                    continue
                keys = (keys_response.json() or {}).get("data") or []
                for key in keys:
                    if (key.get("name") or "").strip() != target_name:
                        continue
                    payload = {
                        "status": "ok",
                        "api_key_id": key.get("id"),
                        "api_key_name": key.get("name"),
                        "api_key_last_used_at": key.get("last_used_at"),
                        "project_id": project_id,
                        "project_name": project.get("name"),
                        "project_api_key_count": len(keys),
                    }
                    self._openai_key_scope_cache = payload
                    self._openai_key_scope_cache_at = now
                    return payload
        payload = {
            "status": "unavailable",
            "reason": "target_api_key_not_found",
            "project_name": self.settings.openai_usage_project_name,
            "api_key_name": self.settings.openai_usage_api_key_name,
        }
        self._openai_key_scope_cache = payload
        self._openai_key_scope_cache_at = now
        return payload

    async def fetch_openai_key_usage(self, *, days: int, api_key_id: str | None) -> dict[str, Any]:
        if not self.settings.openai_admin_key:
            return {"status": "unavailable", "reason": "missing_openai_admin_key", "days": days}
        if not api_key_id:
            return {"status": "unavailable", "reason": "missing_api_key_id", "days": days}
        start = int(time.time()) - (60 * 60 * 24 * days)
        headers = {"Authorization": f"Bearer {self.settings.openai_admin_key.get_secret_value()}"}
        params = [
            ("start_time", str(start)),
            ("bucket_width", "1d"),
            ("limit", str(days)),
            ("api_key_ids[]", api_key_id),
        ]
        try:
            async with httpx.AsyncClient(base_url="https://api.openai.com/v1", timeout=30.0, headers=headers) as client:
                response = await client.get("/organization/usage/completions", params=params)
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            return {"status": "unavailable", "reason": f"http_{exc.response.status_code}", "days": days}
        except (httpx.HTTPError, ValueError):
            return {"status": "unavailable", "reason": "request_failed", "days": days}

        daily: list[dict[str, Any]] = []
        for bucket in raw.get("data", []) or []:
            totals = {
                "date": bucket.get("start_time_iso") or bucket.get("start_time"),
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
            }
            for result in bucket.get("results", []) or []:
                totals["requests"] += int(result.get("num_model_requests") or 0)
                totals["input_tokens"] += int(result.get("input_tokens") or 0)
                totals["output_tokens"] += int(result.get("output_tokens") or 0)
                totals["cached_input_tokens"] += int(result.get("input_cached_tokens") or 0)
            daily.append(totals)

        return {
            "status": "ok",
            "days": days,
            "api_key_id": api_key_id,
            "daily_usage": daily,
            "raw": raw,
        }

    def _extract_bucket_cost_usd(self, bucket: dict[str, Any]) -> float:
        total = 0.0
        for result in bucket.get("results", []) or []:
            amount = result.get("amount")
            if isinstance(amount, dict):
                value = amount.get("value")
                if value is not None:
                    total += float(value)
                    continue
            if amount is not None and isinstance(amount, (int, float)):
                total += float(amount)
                continue
            for key in ("cost_usd", "amount_usd", "total_cost_usd", "cost"):
                value = result.get(key)
                if value is not None:
                    total += float(value)
                    break
        return round(total, 8)

    def _normalize_x_daily_usage(self, daily_project_usage: Any) -> list[dict[str, Any]]:
        daily_rows: list[dict[str, Any]] = []
        if isinstance(daily_project_usage, dict):
            usage_entries = daily_project_usage.get("usage") or []
            if isinstance(usage_entries, list):
                for entry in usage_entries:
                    normalized = self._normalize_x_usage_entry(entry)
                    if normalized is not None:
                        daily_rows.append(normalized)
        elif isinstance(daily_project_usage, list):
            for bucket in daily_project_usage:
                normalized = self._normalize_x_usage_entry(bucket)
                if normalized is not None:
                    daily_rows.append(normalized)
        return sorted(daily_rows, key=lambda item: item["date"])

    def _normalize_x_usage_entry(self, entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        date = entry.get("date")
        if not date:
            return None
        usage = entry.get("usage")
        if isinstance(usage, list):
            consumed = 0
            for item in usage:
                if not isinstance(item, dict):
                    continue
                consumed += self._parse_int(item.get("tweets_consumed")) or 0
        else:
            consumed = self._parse_int(usage) or 0
        return {"date": str(date), "consumed": consumed}

    def _parse_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
