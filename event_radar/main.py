from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from event_radar.classifier import ClassificationUnavailableError
from event_radar.config import Settings, get_settings
from event_radar.db import AccountConflictError
from event_radar.models import (
    AccountCreateRequest,
    AccountUpdateRequest,
    EventVoteRequest,
    ManualEventTestRequest,
    SourcePlatform,
)
from event_radar.service import EventRadarService


LOGGER = logging.getLogger(__name__)
APP_ROOT = Path(__file__).parent
STATIC_ROOT = APP_ROOT / "static"
FRONTEND_INDEX = STATIC_ROOT / "app" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    service: EventRadarService = app.state.service
    await service.start()
    try:
        yield
    finally:
        await service.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app = FastAPI(title="Event Radar", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = EventRadarService(settings)
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return await app.state.service.health()

    @app.get("/api/v1/posts")
    async def api_posts(limit: int = 50) -> list[dict[str, Any]]:
        return await app.state.service.recent_posts(limit=limit)

    @app.get("/api/v1/alerts")
    async def api_alerts(limit: int = 50) -> list[dict[str, Any]]:
        return await app.state.service.recent_alerts(limit=limit)

    @app.get("/api/v1/events")
    async def api_events(
        limit: int = Query(default=50, ge=1, le=100),
        source: SourcePlatform | None = None,
        alert_status: str | None = Query(default=None, max_length=32),
        decision: str | None = Query(default=None, max_length=64),
        q: str | None = Query(default=None, max_length=120),
    ) -> list[dict[str, Any]]:
        return await app.state.service.filtered_events(
            limit=limit,
            source=source,
            alert_status=alert_status,
            decision=decision,
            query=q,
        )

    @app.post("/api/v1/events/test-trigger")
    async def api_test_trigger(request: ManualEventTestRequest) -> dict[str, Any]:
        result = await app.state.service.simulate_event_trigger(request)
        if result is None:
            raise HTTPException(status_code=404, detail="tracked_handle_not_found")
        return result.model_dump(mode="json")

    @app.get("/api/v1/events/stream")
    async def api_stream() -> StreamingResponse:
        service: EventRadarService = app.state.service

        async def event_generator():
            async for queue in service.subscribe_events():
                try:
                    while True:
                        payload = await queue.get()
                        yield f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"
                except asyncio.CancelledError:
                    raise
                finally:
                    break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/events/{normalized_post_id}")
    async def api_event_detail(normalized_post_id: int) -> dict[str, Any]:
        event = await app.state.service.event_detail(normalized_post_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event_not_found")
        return event

    @app.patch("/api/v1/events/{normalized_post_id}/vote")
    async def api_event_vote(normalized_post_id: int, request: EventVoteRequest) -> dict[str, Any]:
        event = await app.state.service.update_event_vote(normalized_post_id, request)
        if event is None:
            raise HTTPException(status_code=404, detail="event_not_found")
        return event

    @app.post("/api/v1/events/{normalized_post_id}/refresh")
    async def api_event_refresh(normalized_post_id: int) -> dict[str, Any]:
        event = await app.state.service.refresh_event(normalized_post_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event_not_found")
        return event

    @app.delete("/api/v1/events/{normalized_post_id}")
    async def api_event_delete(normalized_post_id: int) -> dict[str, Any]:
        deleted = await app.state.service.delete_event(normalized_post_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="event_not_found")
        return {"ok": True, "normalized_post_id": normalized_post_id}

    @app.get("/api/v1/accounts")
    async def api_accounts() -> list[dict[str, Any]]:
        return [account.model_dump(mode="json") for account in await app.state.service.list_accounts()]

    @app.post("/api/v1/accounts")
    async def api_create_account(request: AccountCreateRequest) -> dict[str, Any]:
        account = await app.state.service.create_account(request)
        return account.model_dump(mode="json")

    @app.patch("/api/v1/accounts/{account_id}")
    async def api_update_account(account_id: str, request: AccountUpdateRequest) -> dict[str, Any]:
        account = await app.state.service.update_account(account_id, request)
        if account is None:
            raise HTTPException(status_code=404, detail="account_not_found")
        return account.model_dump(mode="json")

    @app.delete("/api/v1/accounts/{account_id}")
    async def api_delete_account(account_id: str) -> dict[str, Any]:
        account = await app.state.service.delete_account(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="account_not_found")
        return account.model_dump(mode="json")

    @app.get("/api/v1/connectors")
    async def api_connectors() -> list[dict[str, Any]]:
        return await app.state.service.connector_status()

    @app.get("/api/v1/metrics/latency")
    async def api_latency() -> dict[str, Any]:
        return await app.state.service.latency_metrics()

    @app.delete("/api/v1/metrics/latency")
    async def api_reset_latency() -> dict[str, Any]:
        deleted = await app.state.service.reset_latency()
        return {"ok": True, "deleted": deleted}

    @app.get("/api/v1/activity")
    async def api_activity(limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
        return await app.state.service.activity(limit=limit)

    @app.delete("/api/v1/activity")
    async def api_clear_activity() -> dict[str, Any]:
        deleted = await app.state.service.clear_recent_activity()
        return {"ok": True, "deleted": deleted}

    @app.delete("/api/v1/activity/attention")
    async def api_clear_attention() -> dict[str, Any]:
        deleted = await app.state.service.clear_attention_activity()
        return {"ok": True, "deleted": deleted}

    @app.get("/api/v1/dashboard")
    async def api_dashboard() -> dict[str, Any]:
        return await app.state.service.dashboard()

    @app.get("/api/v1/overview")
    async def api_overview() -> dict[str, Any]:
        service = app.state.service
        return {
            "health": await service.health(),
            "connectors": await service.connector_status(),
            "accounts": [account.model_dump(mode="json") for account in await service.list_accounts()],
            "alerts": await service.recent_alerts(limit=12),
            "posts": await service.recent_events(limit=18),
            "activity": await service.activity(limit=40),
            "latency": await service.latency_metrics(),
            "costs": await service.cost_summary(),
        }

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> Response:
        if FRONTEND_INDEX.exists():
            return FileResponse(FRONTEND_INDEX, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<!doctype html><html><body><h1>Frontend build missing</h1>"
            "<p>Run <code>cd frontend && npm install && npm run build</code> to build the dashboard.</p>"
            "</body></html>",
            status_code=503,
        )

    @app.exception_handler(AccountConflictError)
    async def account_conflict_handler(request: Request, exc: AccountConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ClassificationUnavailableError)
    async def classification_unavailable_handler(
        request: Request,
        exc: ClassificationUnavailableError,
    ) -> JSONResponse:
        return JSONResponse({"detail": exc.reason, "message": str(exc)}, status_code=503)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled request error")
        await app.state.service.record_activity(
            "error",
            "error",
            "web",
            "Unhandled request error",
            str(exc),
            {"path": str(request.url.path)},
        )
        return JSONResponse({"detail": "internal_server_error"}, status_code=500)

    return app


app = create_app()
