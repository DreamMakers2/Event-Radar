from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Awaitable, Callable

from event_radar.config import Settings
from event_radar.db import Repository
from event_radar.models import AccountConfig, CanonicalPost, ConnectorStatus


PostHandler = Callable[[str, AccountConfig, CanonicalPost], Awaitable[None]]
ActivityHandler = Callable[[str, str, str, str, str, dict[str, Any] | None], Awaitable[None]]


class BaseConnector(ABC):
    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        on_post: PostHandler,
        on_activity: ActivityHandler | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.on_post = on_post
        self.on_activity = on_activity
        self.logger = logging.getLogger(f"{__name__}.{self.name}")
        self.status = ConnectorStatus(name=self.name, enabled=False)

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def poll_sleep_seconds(self) -> float:
        raise NotImplementedError

    async def sleep_or_stop(self, stop_event: asyncio.Event, seconds: float | None = None) -> bool:
        timeout = self.poll_sleep_seconds if seconds is None else seconds
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def mark_running(self, *, enabled: bool, auth_configured: bool, detail: str | None = None) -> None:
        self.status.enabled = enabled
        self.status.auth_configured = auth_configured
        self.status.running = enabled and auth_configured
        self.status.detail = detail
        self.status.last_error = None

    def mark_error(self, message: str) -> None:
        self.status.last_error = message
        self.status.running = False
        self.status.detail = message
        self.logger.warning("%s connector error: %s", self.name, message)

    def mark_success(self, detail: str | None = None, when: datetime | None = None) -> None:
        self.status.last_success_at = when
        self.status.running = True
        self.status.last_error = None
        if detail:
            self.status.detail = detail

    async def emit_activity(
        self,
        level: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.on_activity is None:
            return
        await self.on_activity("connector", level, self.name, title, message, metadata)

    @abstractmethod
    async def run(self, stop_event: asyncio.Event) -> None:
        raise NotImplementedError
