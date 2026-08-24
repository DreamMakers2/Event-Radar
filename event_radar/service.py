from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from event_radar.billing import BillingService
from event_radar.bus import EventBus
from event_radar.classifier import ClassificationUnavailableError, EventClassifier, extract_usage
from event_radar.config import Settings
from event_radar.connectors.truth_social import TruthSocialConnector
from event_radar.connectors.x import XConnector
from event_radar.db import Repository
from event_radar.instance_lock import EventRadarInstanceLock
from event_radar.models import (
    AccountConfig,
    AccountCreateRequest,
    AccountUpdateRequest,
    ActivityRecord,
    AlertResult,
    AnalysisRecord,
    CanonicalPost,
    EventVoteRequest,
    ManualEventTestAccount,
    ManualEventTestAnalysis,
    ManualEventTestOutcome,
    ManualEventTestRequest,
    ManualEventTestResponse,
    SourcePlatform,
)
from event_radar.relay import TelegramRelayClient
from event_radar.scoring import dedupe_decision
from event_radar.utils import utc_now


LOGGER = logging.getLogger(__name__)


class EventRadarService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = Repository(settings.effective_database_path)
        self.bus = EventBus()
        self.classifier = EventClassifier(settings)
        self.billing = BillingService(settings)
        self.relay = TelegramRelayClient(settings)
        self.instance_lock = EventRadarInstanceLock(settings)
        self.stop_event = asyncio.Event()
        self.started_at = utc_now()
        self._tasks: list[asyncio.Task[None]] = []
        self.connectors = [
            XConnector(settings=settings, repository=self.repository, on_post=self.handle_post, on_activity=self.record_activity),
            TruthSocialConnector(settings=settings, repository=self.repository, on_post=self.handle_post, on_activity=self.record_activity),
        ]

    async def start(self) -> None:
        self.stop_event = asyncio.Event()
        try:
            self.instance_lock.acquire()
            await self.repository.initialize()
            await self.record_activity("system", "info", "service", "Service started", "Event Radar initialized.")
            if self.settings.monitoring_enabled:
                for connector in self.connectors:
                    self._tasks.append(asyncio.create_task(connector.run(self.stop_event)))
        except Exception:
            self.instance_lock.release()
            raise

    async def stop(self) -> None:
        self.stop_event.set()
        try:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            for connector in self.connectors:
                close = getattr(connector, "close", None)
                if close:
                    await close()
            await self.classifier.close()
            await self.relay.close()
            await self.record_activity("system", "info", "service", "Service stopped", "Event Radar shutdown complete.")
        finally:
            self.instance_lock.release()

    async def handle_post(
        self,
        connector_name: str,
        account: AccountConfig,
        post: CanonicalPost,
        *,
        raise_on_classification_error: bool = False,
    ) -> dict[str, Any] | None:
        normalized_post_id, inserted = await self.repository.save_post(post)
        await self.repository.upsert_checkpoint(
            connector_name,
            account.id,
            last_source_post_id=post.source_post_id,
            last_published_at=post.published_at,
            last_observed_at=post.observed_at,
            status="seen",
        )
        if not inserted:
            return None
        await self.record_activity(
            "ingest",
            "info",
            connector_name,
            "Post received",
            f"Received {post.source.value} post from @{post.handle}.",
            {"source_post_id": post.source_post_id, "handle": post.handle, "source": post.source.value},
        )
        classification_started = utc_now()
        await self.repository.update_latency_stage(normalized_post_id, classification_started_at=classification_started)
        try:
            evaluation = await self._evaluate_post(account, post, normalized_post_id=normalized_post_id, allow_delivery=True)
        except ClassificationUnavailableError as exc:
            classification_finished_at = utc_now()
            await self.repository.update_latency_stage(
                normalized_post_id,
                classification_finished_at=classification_finished_at,
            )
            await self.record_activity(
                "classification",
                "error",
                "classifier",
                "Classification failed",
                str(exc),
                {
                    "handle": post.handle,
                    "source_post_id": post.source_post_id,
                    "reason": exc.reason,
                },
            )
            await self.repository.upsert_checkpoint(
                connector_name,
                account.id,
                last_source_post_id=post.source_post_id,
                last_published_at=post.published_at,
                last_observed_at=post.observed_at,
                status="classification_failed",
                detail=exc.reason,
            )
            if raise_on_classification_error:
                raise
            event = await self.repository.get_event(normalized_post_id)
            await self.bus.publish(
                {
                    "type": "event.upsert",
                    "event": event,
                }
            )
            await self.bus.publish({"type": "dashboard.invalidate", "at": classification_finished_at.isoformat()})
            return event

        final = await self._persist_evaluation(
            normalized_post_id=normalized_post_id,
            post=post,
            evaluation=evaluation,
        )
        await self.repository.upsert_checkpoint(
            connector_name,
            account.id,
            last_source_post_id=post.source_post_id,
            last_published_at=post.published_at,
            last_observed_at=post.observed_at,
            status="processed",
            detail=f"alert_id={final['alert_id']}",
        )
        return final["event"]

    async def subscribe_events(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue = await self.bus.add_subscriber()
        try:
            yield queue
        finally:
            await self.bus.remove_subscriber(queue)

    async def record_activity(
        self,
        kind: str,
        level: str,
        component: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = ActivityRecord(
            kind=kind,
            level=level,
            component=component,
            title=title,
            message=message,
            metadata=metadata or {},
            created_at=utc_now(),
        )
        saved = await self.repository.add_activity(record)
        await self.bus.publish({"type": "activity.create", "activity": saved.model_dump(mode="json")})
        connector = await self._connector_update_payload(component)
        if connector is not None:
            await self.bus.publish({"type": "connector.update", "connector": connector})
        await self.bus.publish({"type": "dashboard.invalidate", "at": saved.created_at.isoformat()})

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "started_at": self.started_at.isoformat(),
            "database_path": str(self.settings.effective_database_path),
            "post_count": await self.repository.count_posts(),
            "alert_count": await self.repository.count_alerts(),
            "connectors": [connector.status.model_dump(mode="json") for connector in self.connectors],
        }

    async def connector_status(self) -> list[dict[str, Any]]:
        checkpoints = await self.repository.connector_checkpoint_snapshot()
        return [
            {
                **connector.status.model_dump(mode="json"),
                "checkpoints": [checkpoint for checkpoint in checkpoints if checkpoint["connector"] == connector.name],
            }
            for connector in self.connectors
        ]

    async def recent_posts(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.repository.recent_posts(limit=limit)

    async def recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.repository.recent_alerts(limit=limit)

    async def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.repository.recent_events(limit=limit)

    async def filtered_events(
        self,
        *,
        limit: int = 50,
        source: SourcePlatform | None = None,
        alert_status: str | None = None,
        decision: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.repository.recent_events(
            min(max(limit, 1), 100),
            source=source,
            alert_status=alert_status.strip() if alert_status else None,
            decision=decision.strip() if decision else None,
            query=query.strip() if query else None,
        )

    async def event_detail(self, normalized_post_id: int) -> dict[str, Any] | None:
        return await self.repository.get_event(normalized_post_id)

    async def latency_metrics(self) -> dict[str, Any]:
        return await self.repository.latency_metrics()

    async def activity(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.repository.recent_activity(limit=limit)

    async def dashboard(self) -> dict[str, Any]:
        health = await self.health()
        connectors = await self.connector_status()
        accounts = [account.model_dump(mode="json") for account in await self.list_accounts()]
        activity = await self.activity(limit=30)
        attention = [item for item in activity if item["level"] in {"warning", "error"}][:8]
        latency = await self.latency_metrics()
        costs = await self.cost_summary()
        summary = {
            "status": health["status"],
            "started_at": health["started_at"],
            "database_path": health["database_path"],
            "post_count": health["post_count"],
            "alert_count": health["alert_count"],
            "connector_count": len(connectors),
            "running_connector_count": sum(1 for connector in connectors if connector["running"]),
            "attention_count": len(attention),
            "last_activity_at": activity[0]["created_at"] if activity else None,
        }
        return {
            "summary": summary,
            "connectors": connectors,
            "latency": latency,
            "costs": costs,
            "attention": attention,
            "activity": activity[:12],
            "accounts": accounts,
        }

    async def cost_summary(self) -> dict[str, Any]:
        now = utc_now()
        x_request_usage_last_7d = await self.repository.api_request_summary(
            provider="x",
            request_kind="read",
            since=now - timedelta(days=7),
        )
        x_request_usage_last_30d = await self.repository.api_request_summary(
            provider="x",
            request_kind="read",
            since=now - timedelta(days=30),
        )
        openai_local_usage_last_7d = await self.repository.usage_summary(since=now - timedelta(days=7))
        openai_local_usage_last_30d = await self.repository.usage_summary(since=now - timedelta(days=30))
        eur_per_usd, fx_reference_date = await self.billing.eur_per_usd()
        credit = await self.billing.fetch_available_credit()
        openai_scope = await self.billing.resolve_openai_api_key_scope()
        x_post_usage = await self.billing.fetch_x_post_usage(days=30)
        openai_last_7d = self._summarize_openai_local_usage(openai_local_usage_last_7d)
        openai_last_30d = self._summarize_openai_local_usage(openai_local_usage_last_30d)
        estimated_last_7d_usd = round(float(openai_local_usage_last_7d.get("request_cost_usd") or 0.0), 8)
        estimated_last_30d_usd = round(float(openai_local_usage_last_30d.get("request_cost_usd") or 0.0), 8)
        projected_monthly_cost_eur = round(estimated_last_30d_usd * eur_per_usd, 2)
        billed_costs = {
            "status": "unavailable",
            "reason": "api_key_cost_isolation_unavailable",
            "billed_last_7d_usd": None,
            "billed_last_7d_eur": None,
            "billed_last_30d_usd": None,
            "billed_last_30d_eur": None,
            "window_days": None,
        }
        if openai_scope.get("status") == "ok" and int(openai_scope.get("project_api_key_count") or 0) == 1:
            project_costs = await self.billing.fetch_organization_costs(days=31, project_ids=[openai_scope["project_id"]])
            if project_costs.get("status") == "ok":
                billed_last_30d_usd = float(project_costs.get("billed_last_30d_usd") or 0.0)
                if estimated_last_30d_usd > 0 and billed_last_30d_usd == 0.0:
                    billed_costs["reason"] = "configured_project_no_recent_activity"
                else:
                    billed_costs = {
                        "status": "ok",
                        "reason": None,
                        "billed_last_7d_usd": project_costs.get("billed_last_7d_usd"),
                        "billed_last_7d_eur": round(float(project_costs["billed_last_7d_usd"]) * eur_per_usd, 2),
                        "billed_last_30d_usd": project_costs.get("billed_last_30d_usd"),
                        "billed_last_30d_eur": round(billed_last_30d_usd * eur_per_usd, 2),
                        "window_days": project_costs.get("days"),
                    }
            else:
                billed_costs["reason"] = project_costs.get("reason") or "project_cost_lookup_failed"
        available_credit_eur = None
        if credit.get("status") == "ok":
            available_credit_eur = round(float(credit["available_credit_usd"]) * eur_per_usd, 2)
        return {
            "fx": {
                "eur_per_usd": eur_per_usd,
                "reference_date": fx_reference_date,
            },
            "openai": {
                "model": self.settings.openai_model,
                "scope": {
                    "status": openai_scope.get("status"),
                    "reason": openai_scope.get("reason"),
                    "api_key_name": openai_scope.get("api_key_name") or self.settings.openai_usage_api_key_name,
                    "api_key_id": openai_scope.get("api_key_id"),
                    "api_key_last_used_at": openai_scope.get("api_key_last_used_at"),
                    "project_id": openai_scope.get("project_id"),
                    "project_name": openai_scope.get("project_name"),
                    "project_api_key_count": openai_scope.get("project_api_key_count"),
                },
                "pricing": {
                    "input_cost_per_million_usd": self.settings.openai_input_cost_per_million_usd,
                    "output_cost_per_million_usd": self.settings.openai_output_cost_per_million_usd,
                    "cached_input_cost_per_million_usd": self.settings.openai_cached_input_cost_per_million_usd,
                },
                "usage": {
                    "status": "ok",
                    "reason": None,
                    "last_7d": openai_last_7d,
                    "last_30d": openai_last_30d,
                },
                "costs": {
                    "estimated_last_7d_usd": estimated_last_7d_usd,
                    "estimated_last_7d_eur": round(estimated_last_7d_usd * eur_per_usd, 4),
                    "estimated_last_30d_usd": estimated_last_30d_usd,
                    "estimated_last_30d_eur": round(estimated_last_30d_usd * eur_per_usd, 4),
                    "projected_monthly_cost_eur": projected_monthly_cost_eur,
                },
                "billed_costs": billed_costs,
                "credit": {
                    "status": credit.get("status"),
                    "reason": credit.get("reason"),
                    "available_credit_usd": credit.get("available_credit_usd"),
                    "available_credit_eur": available_credit_eur,
                },
            },
            "x": {
                "official_usage": {
                    "status": x_post_usage.get("status"),
                    "reason": x_post_usage.get("reason"),
                    "project_id": x_post_usage.get("project_id"),
                    "project_cap": x_post_usage.get("project_cap"),
                    "project_usage": x_post_usage.get("project_usage"),
                    "cap_reset_day": x_post_usage.get("cap_reset_day"),
                    "consumed_last_7d": x_post_usage.get("consumed_last_7d"),
                    "consumed_last_30d": x_post_usage.get("consumed_last_30d"),
                    "daily_usage": x_post_usage.get("daily_usage") or [],
                },
                "local_usage": {
                    "read_requests_last_7d": int(x_request_usage_last_7d["request_count"] or 0),
                    "read_requests_last_30d": int(x_request_usage_last_30d["request_count"] or 0),
                    "successful_read_requests_last_7d": int(x_request_usage_last_7d["successful_request_count"] or 0),
                    "successful_read_requests_last_30d": int(x_request_usage_last_30d["successful_request_count"] or 0),
                },
            },
        }

    def _summarize_openai_key_usage(self, daily_usage: list[dict[str, Any]]) -> dict[str, Any]:
        analysis_count = sum(int(item.get("requests") or 0) for item in daily_usage)
        input_tokens = sum(int(item.get("input_tokens") or 0) for item in daily_usage)
        output_tokens = sum(int(item.get("output_tokens") or 0) for item in daily_usage)
        cached_input_tokens = sum(int(item.get("cached_input_tokens") or 0) for item in daily_usage)
        total_tokens = input_tokens + output_tokens
        average_total_tokens_per_request = round(total_tokens / analysis_count, 1) if analysis_count else None
        average_input_tokens_per_request = round(input_tokens / analysis_count, 1) if analysis_count else None
        average_output_tokens_per_request = round(output_tokens / analysis_count, 1) if analysis_count else None
        return {
            "analysis_count": analysis_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "total_tokens": total_tokens,
            "average_total_tokens_per_request": average_total_tokens_per_request,
            "average_input_tokens_per_request": average_input_tokens_per_request,
            "average_output_tokens_per_request": average_output_tokens_per_request,
        }

    def _summarize_openai_local_usage(self, usage_summary: dict[str, Any]) -> dict[str, Any]:
        analysis_count = int(usage_summary.get("analysis_count") or 0)
        input_tokens = int(usage_summary.get("input_tokens") or 0)
        output_tokens = int(usage_summary.get("output_tokens") or 0)
        cached_input_tokens = int(usage_summary.get("cached_input_tokens") or 0)
        total_tokens = input_tokens + output_tokens
        average_total_tokens_per_request = round(total_tokens / analysis_count, 1) if analysis_count else None
        average_input_tokens_per_request = round(input_tokens / analysis_count, 1) if analysis_count else None
        average_output_tokens_per_request = round(output_tokens / analysis_count, 1) if analysis_count else None
        return {
            "analysis_count": analysis_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "total_tokens": total_tokens,
            "average_total_tokens_per_request": average_total_tokens_per_request,
            "average_input_tokens_per_request": average_input_tokens_per_request,
            "average_output_tokens_per_request": average_output_tokens_per_request,
            "first_analysis_at": usage_summary.get("first_analysis_at"),
            "last_analysis_at": usage_summary.get("last_analysis_at"),
        }

    async def list_accounts(self) -> list[AccountConfig]:
        return await self.repository.list_accounts()

    async def create_account(self, request: AccountCreateRequest) -> AccountConfig:
        return await self.repository.create_account(request)

    async def update_account(self, account_id: str, request: AccountUpdateRequest) -> AccountConfig | None:
        return await self.repository.update_account(account_id, request)

    async def delete_account(self, account_id: str) -> AccountConfig | None:
        account = await self.repository.delete_account(account_id)
        if account is None:
            return None
        await self.record_activity(
            "configuration",
            "info",
            "accounts",
            "Tracked account removed",
            f"Stopped tracking @{account.handle} on {account.source.value}.",
            {"account_id": account.id, "handle": account.handle, "source": account.source.value},
        )
        return account

    async def simulate_event_trigger(self, request: ManualEventTestRequest) -> ManualEventTestResponse | None:
        account = await self.repository.find_account_by_handle(request.handle)
        if account is None:
            return None
        now = utc_now()
        post = CanonicalPost(
            source=account.source,
            account_db_id=account.id,
            source_account_id=account.source_account_id or account.id,
            display_name=account.display_name,
            handle=account.handle,
            source_post_id=f"manual-test-{uuid4().hex}",
            canonical_url=account.source_url,
            text=request.message,
            published_at=now,
            observed_at=now,
            raw_payload={"kind": "manual_test", "handle": account.handle, "source": account.source.value},
            collector_metadata={"manual_test": True},
        )
        event = await self.handle_post("manual_test", account, post, raise_on_classification_error=True)
        if event is None:
            return None
        analysis = event["analysis"]
        alert = event["alert"]
        alert_status = alert["status"] if alert else "suppressed"
        would_notify = alert_status in {"sent", "dry_run"}
        response = ManualEventTestResponse(
            account=ManualEventTestAccount(
                id=account.id,
                source=account.source,
                display_name=account.display_name,
                handle=account.handle,
                authority_rank=account.authority_rank,
                alert_threshold=account.alert_threshold,
                active=account.active,
            ),
            analysis=ManualEventTestAnalysis(
                mode="model",
                summary=analysis["summary"] or post.text,
                categories=analysis["categories"],
                reasoning=analysis["reasoning"] or "",
                breakdown=analysis["breakdown"],
                market_impacts=analysis["market_impacts"],
                total_score=float(analysis["total_score"] or 0.0),
                threshold=int(analysis["threshold"] or (account.alert_threshold or self.settings.alert_threshold)),
                decision=analysis["decision"] or "",
                request_cost_usd=float(analysis["request_cost_usd"] or 0.0),
            ),
            outcome=ManualEventTestOutcome(
                would_notify=would_notify,
                status=alert_status,
                reason=alert["suppression_reason"] if alert else None,
                message_text=self._manual_test_outcome_message(alert_status, alert),
            ),
        )
        await self.record_activity(
            "manual_test",
            "info",
            "manual_test",
            "Manual trigger evaluated",
            f"@{account.handle} manual test stored with status {alert_status}.",
            {
                "account_id": account.id,
                "handle": account.handle,
                "source": account.source.value,
                "decision": analysis["decision"],
                "would_notify": would_notify,
                "alert_status": alert_status,
            },
        )
        return response

    async def update_event_vote(self, normalized_post_id: int, request: EventVoteRequest) -> dict[str, Any] | None:
        saved_vote = await self.repository.save_event_vote(normalized_post_id, request.vote)
        if saved_vote is None:
            return None
        event = await self.repository.get_event(normalized_post_id)
        if event is None:
            return None
        await self.bus.publish({"type": "event.upsert", "event": event})
        return event

    async def refresh_event(self, normalized_post_id: int) -> dict[str, Any] | None:
        post = await self.repository.get_canonical_post(normalized_post_id)
        if post is None:
            return None
        account = await self.repository.get_account(post.account_db_id)
        if account is None:
            return None

        refreshed_at = utc_now()
        replay_post = post.model_copy(
            update={
                "observed_at": refreshed_at,
                "collector_metadata": {
                    **post.collector_metadata,
                    "manual_refresh": True,
                    "manual_refresh_at": refreshed_at.isoformat(),
                },
            }
        )
        await self.record_activity(
            "event_operation",
            "info",
            "events",
            "Event refresh started",
            f"Refreshing event for @{replay_post.handle} with duplicate suppression bypassed.",
            {"normalized_post_id": normalized_post_id, "handle": replay_post.handle},
        )
        await self.repository.update_latency_stage(
            normalized_post_id,
            classification_started_at=refreshed_at,
            classification_finished_at=None,
            relay_sent_at=None,
            relay_acked_at=None,
        )
        try:
            evaluation = await self._evaluate_post(
                account,
                replay_post,
                normalized_post_id=normalized_post_id,
                allow_delivery=True,
                bypass_backfill=True,
                bypass_duplicate_suppression=True,
            )
        except ClassificationUnavailableError as exc:
            classification_finished_at = utc_now()
            await self.repository.update_latency_stage(
                normalized_post_id,
                classification_finished_at=classification_finished_at,
            )
            await self.record_activity(
                "classification",
                "error",
                "classifier",
                "Refresh classification failed",
                str(exc),
                {
                    "normalized_post_id": normalized_post_id,
                    "handle": replay_post.handle,
                    "reason": exc.reason,
                },
            )
            raise
        final = await self._persist_evaluation(
            normalized_post_id=normalized_post_id,
            post=replay_post,
            evaluation=evaluation,
        )
        await self.record_activity(
            "event_operation",
            "info",
            "events",
            "Event refreshed",
            f"Event for @{replay_post.handle} refreshed with decision {evaluation['decision']}.",
            {
                "normalized_post_id": normalized_post_id,
                "handle": replay_post.handle,
                "decision": evaluation["decision"],
                "score": evaluation["total_score"],
            },
        )
        return final["event"]

    async def delete_event(self, normalized_post_id: int) -> bool:
        event = await self.repository.get_event(normalized_post_id)
        if event is None:
            return False
        deleted = await self.repository.delete_event(normalized_post_id)
        if not deleted:
            return False
        await self.record_activity(
            "event_operation",
            "info",
            "events",
            "Event deleted",
            f"Deleted stored event for @{event['handle']}.",
            {"normalized_post_id": normalized_post_id, "handle": event["handle"]},
        )
        await self.bus.publish({"type": "event.delete", "normalized_post_id": normalized_post_id})
        await self.bus.publish({"type": "dashboard.invalidate", "at": utc_now().isoformat()})
        return True

    async def clear_recent_activity(self) -> int:
        deleted = await self.repository.clear_activity()
        await self.bus.publish({"type": "dashboard.invalidate", "at": utc_now().isoformat()})
        return deleted

    async def clear_attention_activity(self) -> int:
        deleted = await self.repository.clear_activity(levels=("warning", "error"))
        await self.bus.publish({"type": "dashboard.invalidate", "at": utc_now().isoformat()})
        return deleted

    async def reset_latency(self) -> int:
        deleted = await self.repository.reset_latency_samples()
        await self.bus.publish({"type": "dashboard.invalidate", "at": utc_now().isoformat()})
        return deleted

    async def _connector_update_payload(self, component: str) -> dict[str, Any] | None:
        if component not in {connector.name for connector in self.connectors}:
            return None
        for connector in await self.connector_status():
            if connector["name"] == component:
                return connector
        return None

    async def _evaluate_post(
        self,
        account: AccountConfig,
        post: CanonicalPost,
        *,
        allow_delivery: bool,
        normalized_post_id: int | None = None,
        bypass_backfill: bool = False,
        bypass_duplicate_suppression: bool = False,
    ) -> dict[str, Any]:
        classifier_output, total_score, raw_response = await self.classifier.analyze(post)
        classification_finished_at = utc_now()
        usage = extract_usage(raw_response)
        request_cost_usd = self.billing.estimate_cost_usd(**usage)
        threshold = account.alert_threshold or self.settings.alert_threshold
        alert_allowed_after = self.started_at - timedelta(minutes=self.settings.historical_backfill_alert_minutes)
        if not bypass_backfill and post.published_at < alert_allowed_after:
            decision = "historical_backfill"
            alert_result = AlertResult(
                status="suppressed",
                message_text="Historical post stored without alerting.",
                suppression_reason="historical_backfill",
            )
        elif total_score < threshold:
            decision = "below_threshold"
            alert_result = AlertResult(
                status="suppressed",
                message_text="Below threshold; stored without alerting.",
                suppression_reason="below_threshold",
            )
        else:
            if bypass_duplicate_suppression:
                alert_decision = None
            else:
                candidates = await self.repository.recent_duplicate_candidates(
                    account.entity_key,
                    within_minutes=self.settings.duplicate_window_minutes,
                )
                alert_decision = dedupe_decision(
                    post,
                    total_score,
                    account.authority_rank,
                    candidates,
                    minimum_score_delta=self.settings.duplicate_score_delta,
                )
            if bypass_duplicate_suppression or (alert_decision is not None and alert_decision.should_alert):
                decision = "alerted"
                if allow_delivery:
                    analysis_preview = AnalysisRecord(
                        normalized_post_id=normalized_post_id or 0,
                        model=self.settings.openai_model,
                        summary=classifier_output.summary,
                        categories=classifier_output.categories,
                        reasoning=classifier_output.reasoning,
                        breakdown=classifier_output.breakdown,
                        market_impacts=classifier_output.market_impacts,
                        total_score=total_score,
                        threshold=threshold,
                        decision=decision,
                        raw_response=raw_response,
                        created_at=utc_now(),
                    )
                    try:
                        alert_result = await self.relay.send_alert(account=account, post=post, analysis=analysis_preview)
                    except Exception as exc:  # noqa: BLE001
                        decision = "alert_failed"
                        alert_result = AlertResult(
                            status="failed",
                            message_text="Relay send failed.",
                            suppression_reason=str(exc),
                        )
                        await self.record_activity(
                            "alert",
                            "error",
                            "relay",
                            "Relay send failed",
                            str(exc),
                            {"handle": post.handle, "source_post_id": post.source_post_id},
                        )
                else:
                    alert_result = AlertResult(
                        status="dry_run",
                        message_text="Manual test would trigger a notification.",
                    )
            else:
                assert alert_decision is not None
                decision = alert_decision.reason
                alert_result = AlertResult(
                    status="suppressed",
                    message_text="Duplicate event suppressed." if allow_delivery else "Manual test would be suppressed as duplicate.",
                    suppression_reason=alert_decision.reason,
                )
        return {
            "classifier_output": classifier_output,
            "total_score": total_score,
            "raw_response": raw_response,
            "usage": usage,
            "request_cost_usd": request_cost_usd,
            "threshold": threshold,
            "decision": decision,
            "alert_result": alert_result,
            "classification_finished_at": classification_finished_at,
        }

    async def _persist_evaluation(
        self,
        *,
        normalized_post_id: int,
        post: CanonicalPost,
        evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        await self.repository.update_latency_stage(
            normalized_post_id,
            classification_finished_at=evaluation["classification_finished_at"],
            relay_sent_at=evaluation["alert_result"].sent_at,
            relay_acked_at=evaluation["alert_result"].acked_at,
        )
        classifier_output = evaluation["classifier_output"]
        total_score = evaluation["total_score"]
        raw_response = evaluation["raw_response"]
        usage = evaluation["usage"]
        request_cost_usd = evaluation["request_cost_usd"]
        threshold = evaluation["threshold"]
        decision = evaluation["decision"]
        alert_result = evaluation["alert_result"]
        analysis = AnalysisRecord(
            normalized_post_id=normalized_post_id,
            model=self.settings.openai_model,
            summary=classifier_output.summary,
            categories=classifier_output.categories,
            reasoning=classifier_output.reasoning,
            breakdown=classifier_output.breakdown,
            market_impacts=classifier_output.market_impacts,
            total_score=total_score,
            threshold=threshold,
            decision=decision,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            request_cost_usd=request_cost_usd,
            raw_response=raw_response,
            created_at=utc_now(),
        )
        await self.record_activity(
            "classification",
            "info",
            "classifier",
            "Post classified",
            f"@{post.handle} classified with score {total_score:.2f} and decision {decision}.",
            {
                "handle": post.handle,
                "source_post_id": post.source_post_id,
                "score": total_score,
                "decision": decision,
                "categories": classifier_output.categories,
                "summary": classifier_output.summary,
                "request_cost_usd": request_cost_usd,
            },
        )
        analysis_id = await self.repository.save_analysis(analysis)
        alert_id = await self.repository.save_alert(normalized_post_id, analysis_id, alert_result)
        await self.record_activity(
            "alert",
            "info" if alert_result.status in {"sent", "dry_run"} else "warning",
            "relay",
            "Alert decision",
            f"@{post.handle} -> {alert_result.status}",
            {
                "handle": post.handle,
                "source_post_id": post.source_post_id,
                "status": alert_result.status,
                "suppression_reason": alert_result.suppression_reason,
            },
        )
        event = await self.repository.get_event(normalized_post_id)
        await self.bus.publish({"type": "event.upsert", "event": event})
        await self.bus.publish({"type": "dashboard.invalidate", "at": utc_now().isoformat()})
        return {"event": event, "alert_id": alert_id}

    @staticmethod
    def _manual_test_outcome_message(alert_status: str, alert: dict[str, Any] | None) -> str:
        if alert_status == "sent":
            return "Alert sent to relay."
        if alert_status == "dry_run":
            return "Alert accepted in dry-run mode."
        if alert:
            return str(alert.get("message_text") or alert_status)
        return alert_status
