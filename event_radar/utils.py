from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_shell_exports(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            value = raw_value[1:-1]
        else:
            value = raw_value
        values[key] = value
    return values


def env_lookup(source: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name in source and source[name] != "":
            return source[name]
    return None


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    return int(value)


def parse_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def isoformat_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def json_loads(data: str | None, default: Any) -> Any:
    if not data:
        return default
    return json.loads(data)


TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_html_text(value: str) -> str:
    text = html.unescape(TAG_RE.sub(" ", value or ""))
    return WHITESPACE_RE.sub(" ", text).strip()


def numeric_like_id(value: str | None) -> int | None:
    if value and value.isdigit():
        return int(value)
    return None


def is_newer_id(candidate: str | None, baseline: str | None) -> bool:
    if candidate is None:
        return False
    if baseline is None:
        return True
    left = numeric_like_id(candidate)
    right = numeric_like_id(baseline)
    if left is not None and right is not None:
        return left > right
    return candidate > baseline


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def split_cookie_header(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for chunk in value.split(";"):
        if "=" not in chunk:
            continue
        key, raw = chunk.split("=", 1)
        cookies[key.strip()] = raw.strip()
    return cookies


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def getenv() -> dict[str, str]:
    return dict(os.environ)

