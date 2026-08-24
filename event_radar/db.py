from __future__ import annotations

import math
from contextlib import asynccontextmanager
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from event_radar.accounts import seed_accounts
from event_radar.models import (
    AccountConfig,
    AccountCreateRequest,
    AccountUpdateRequest,
    ActivityRecord,
    AlertResult,
    AnalysisRecord,
    CanonicalPost,
    EventFeedbackVote,
    EventVoteRecord,
    MarketImpactSnapshot,
    SourcePlatform,
)
from event_radar.scoring import DuplicateCandidate
from event_radar.utils import isoformat_or_none, json_dumps, json_loads, parse_datetime, utc_now


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        entity_key TEXT NOT NULL,
        display_name TEXT NOT NULL,
        handle TEXT NOT NULL,
        source_account_id TEXT,
        source_url TEXT,
        official INTEGER NOT NULL,
        active INTEGER NOT NULL,
        authority_rank INTEGER NOT NULL,
        alert_threshold INTEGER,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(source, handle)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        account_id TEXT NOT NULL,
        source_post_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(source, source_post_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS normalized_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_post_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        account_id TEXT NOT NULL,
        source_account_id TEXT NOT NULL,
        source_post_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        handle TEXT NOT NULL,
        canonical_url TEXT,
        text TEXT NOT NULL,
        links_json TEXT NOT NULL,
        media_urls_json TEXT NOT NULL,
        is_reply INTEGER NOT NULL,
        is_repost INTEGER NOT NULL,
        published_at TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        collector_metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(source, source_post_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        normalized_post_id INTEGER NOT NULL UNIQUE,
        model TEXT NOT NULL,
        summary TEXT NOT NULL,
        categories_json TEXT NOT NULL,
        reasoning TEXT NOT NULL,
        market_impacts_json TEXT NOT NULL DEFAULT '{}',
        actor_importance INTEGER NOT NULL,
        event_severity INTEGER NOT NULL,
        immediacy INTEGER NOT NULL,
        novelty INTEGER NOT NULL,
        wider_impact INTEGER NOT NULL,
        total_score REAL NOT NULL,
        threshold INTEGER NOT NULL,
        decision TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cached_input_tokens INTEGER NOT NULL DEFAULT 0,
        request_cost_usd REAL NOT NULL DEFAULT 0,
        raw_response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        normalized_post_id INTEGER NOT NULL UNIQUE,
        analysis_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        message_text TEXT NOT NULL,
        suppression_reason TEXT,
        relay_response_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        acked_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS connector_checkpoints (
        connector TEXT NOT NULL,
        account_id TEXT NOT NULL,
        last_source_post_id TEXT,
        last_published_at TEXT,
        last_observed_at TEXT,
        status TEXT,
        detail TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(connector, account_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS latency_samples (
        normalized_post_id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_post_id TEXT NOT NULL,
        source_published_at TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        persisted_at TEXT,
        classification_started_at TEXT,
        classification_finished_at TEXT,
        relay_sent_at TEXT,
        relay_acked_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        level TEXT NOT NULL,
        component TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_feedback_votes (
        normalized_post_id INTEGER PRIMARY KEY,
        vote TEXT NOT NULL CHECK (vote IN ('up', 'down')),
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_request_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        method TEXT NOT NULL,
        request_kind TEXT NOT NULL,
        status_code INTEGER,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]

MIGRATION_STATEMENTS = [
    "ALTER TABLE analyses ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE analyses ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE analyses ADD COLUMN cached_input_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE analyses ADD COLUMN request_cost_usd REAL NOT NULL DEFAULT 0",
    "ALTER TABLE analyses ADD COLUMN market_impacts_json TEXT NOT NULL DEFAULT '{}'",
]


class AccountConflictError(Exception):
    pass


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.database_path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA journal_mode=WAL;")
        await connection.execute("PRAGMA foreign_keys=ON;")
        return connection

    @asynccontextmanager
    async def connection(self):
        conn = await self.connect()
        try:
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        async with self.connection() as conn:
            for statement in SCHEMA_STATEMENTS:
                await conn.execute(statement)
            for statement in MIGRATION_STATEMENTS:
                try:
                    await conn.execute(statement)
                except aiosqlite.OperationalError:
                    pass
            await conn.commit()
        await self.seed_default_accounts()

    async def seed_default_accounts(self) -> None:
        existing = await self.list_accounts()
        if existing:
            return
        async with self.connection() as conn:
            for account in seed_accounts():
                await self._insert_account(conn, account)
            await conn.commit()

    async def list_accounts(self, *, active_only: bool = False, source: SourcePlatform | None = None) -> list[AccountConfig]:
        clauses = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = 1")
        if source:
            clauses.append("source = ?")
            params.append(source.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM accounts {where} ORDER BY authority_rank DESC, display_name ASC"
        async with self.connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_account(row) for row in rows]

    async def get_account(self, account_id: str) -> AccountConfig | None:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = await cursor.fetchone()
        return self._row_to_account(row) if row else None

    async def find_account_by_handle(self, handle: str) -> AccountConfig | None:
        normalized_handle = handle.strip().lstrip("@").lower()
        async with self.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT *
                FROM accounts
                WHERE LOWER(handle) = ?
                ORDER BY active DESC, authority_rank DESC, updated_at DESC
                LIMIT 1
                """,
                (normalized_handle,),
            )
            row = await cursor.fetchone()
        return self._row_to_account(row) if row else None

    async def create_account(self, request: AccountCreateRequest) -> AccountConfig:
        now = utc_now()
        identifier = f"custom_{request.source.value}_{request.handle.lower()}"
        account = AccountConfig(
            id=identifier,
            source=request.source,
            entity_key=request.entity_key,
            display_name=request.display_name,
            handle=request.handle,
            source_account_id=request.source_account_id,
            source_url=request.source_url,
            official=request.official,
            active=request.active,
            authority_rank=request.authority_rank,
            alert_threshold=request.alert_threshold,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )
        async with self.connection() as conn:
            try:
                await self._insert_account(conn, account)
                await conn.commit()
            except aiosqlite.IntegrityError as exc:
                raise AccountConflictError("account_already_exists") from exc
        return account

    async def update_account(self, account_id: str, request: AccountUpdateRequest) -> AccountConfig | None:
        current = await self.get_account(account_id)
        if current is None:
            return None
        changed_fields = request.model_fields_set
        updated = current.model_copy(
            update={
                "active": current.active if "active" not in changed_fields else request.active,
                "alert_threshold": current.alert_threshold
                if "alert_threshold" not in changed_fields
                else request.alert_threshold,
                "source_account_id": current.source_account_id
                if "source_account_id" not in changed_fields
                else request.source_account_id,
                "authority_rank": current.authority_rank
                if "authority_rank" not in changed_fields
                else request.authority_rank,
                "metadata": current.metadata if "metadata" not in changed_fields else request.metadata,
                "updated_at": utc_now(),
            }
        )
        async with self.connection() as conn:
            await conn.execute(
                """
                UPDATE accounts
                SET active = ?, alert_threshold = ?, source_account_id = ?, authority_rank = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if updated.active else 0,
                    updated.alert_threshold,
                    updated.source_account_id,
                    updated.authority_rank,
                    json_dumps(updated.metadata),
                    updated.updated_at.isoformat(),
                    account_id,
                ),
            )
            await conn.commit()
        return updated

    async def delete_account(self, account_id: str) -> AccountConfig | None:
        current = await self.get_account(account_id)
        if current is None:
            return None
        async with self.connection() as conn:
            await conn.execute("DELETE FROM connector_checkpoints WHERE account_id = ?", (account_id,))
            await conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            await conn.commit()
        return current

    async def resolve_account_identity(self, account_id: str, source_account_id: str, source_url: str | None = None) -> None:
        now = utc_now().isoformat()
        async with self.connection() as conn:
            await conn.execute(
                "UPDATE accounts SET source_account_id = ?, source_url = COALESCE(?, source_url), updated_at = ? WHERE id = ?",
                (source_account_id, source_url, now, account_id),
            )
            await conn.commit()

    async def save_post(self, post: CanonicalPost) -> tuple[int, bool]:
        created_at = utc_now().isoformat()
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO raw_posts (source, account_id, source_post_id, payload_json, observed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    post.source.value,
                    post.account_db_id,
                    post.source_post_id,
                    json_dumps(post.raw_payload),
                    post.observed_at.isoformat(),
                    created_at,
                ),
            )
            cursor = await conn.execute(
                "SELECT id FROM raw_posts WHERE source = ? AND source_post_id = ?",
                (post.source.value, post.source_post_id),
            )
            raw_row = await cursor.fetchone()
            raw_post_id = int(raw_row["id"])
            before = conn.total_changes
            await conn.execute(
                """
                INSERT OR IGNORE INTO normalized_posts (
                    raw_post_id, source, account_id, source_account_id, source_post_id, display_name, handle, canonical_url,
                    text, links_json, media_urls_json, is_reply, is_repost, published_at, observed_at, collector_metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_post_id,
                    post.source.value,
                    post.account_db_id,
                    post.source_account_id,
                    post.source_post_id,
                    post.display_name,
                    post.handle,
                    post.canonical_url,
                    post.text,
                    json_dumps(post.links),
                    json_dumps(post.media_urls),
                    1 if post.is_reply else 0,
                    1 if post.is_repost else 0,
                    post.published_at.isoformat(),
                    post.observed_at.isoformat(),
                    json_dumps(post.collector_metadata),
                    created_at,
                ),
            )
            inserted = conn.total_changes > before
            cursor = await conn.execute(
                "SELECT id FROM normalized_posts WHERE source = ? AND source_post_id = ?",
                (post.source.value, post.source_post_id),
            )
            row = await cursor.fetchone()
            normalized_post_id = int(row["id"])
            await conn.execute(
                """
                INSERT INTO latency_samples (normalized_post_id, source, source_post_id, source_published_at, observed_at, persisted_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_post_id) DO UPDATE SET
                    observed_at = excluded.observed_at,
                    persisted_at = COALESCE(latency_samples.persisted_at, excluded.persisted_at),
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_post_id,
                    post.source.value,
                    post.source_post_id,
                    post.published_at.isoformat(),
                    post.observed_at.isoformat(),
                    utc_now().isoformat(),
                    utc_now().isoformat(),
                ),
            )
            await conn.commit()
        return normalized_post_id, inserted

    async def save_analysis(self, record: AnalysisRecord) -> int:
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO analyses (
                    normalized_post_id, model, summary, categories_json, reasoning, market_impacts_json,
                    actor_importance, event_severity, immediacy, novelty, wider_impact,
                    total_score, threshold, decision, input_tokens, output_tokens,
                    cached_input_tokens, request_cost_usd, raw_response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.normalized_post_id,
                    record.model,
                    record.summary,
                    json_dumps(record.categories),
                    record.reasoning,
                    json_dumps(record.market_impacts.model_dump(mode="json")),
                    record.breakdown.actor_importance,
                    record.breakdown.event_severity,
                    record.breakdown.immediacy,
                    record.breakdown.novelty,
                    record.breakdown.wider_impact,
                    record.total_score,
                    record.threshold,
                    record.decision,
                    record.input_tokens,
                    record.output_tokens,
                    record.cached_input_tokens,
                    record.request_cost_usd,
                    json_dumps(record.raw_response),
                    record.created_at.isoformat(),
                ),
            )
            cursor = await conn.execute("SELECT id FROM analyses WHERE normalized_post_id = ?", (record.normalized_post_id,))
            row = await cursor.fetchone()
            await conn.commit()
        return int(row["id"])

    async def save_alert(self, normalized_post_id: int, analysis_id: int, alert: AlertResult) -> int:
        created_at = utc_now().isoformat()
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO alerts (
                    normalized_post_id, analysis_id, status, message_text, suppression_reason, relay_response_json, created_at, sent_at, acked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_post_id,
                    analysis_id,
                    alert.status,
                    alert.message_text,
                    alert.suppression_reason,
                    json_dumps(alert.relay_response),
                    created_at,
                    isoformat_or_none(alert.sent_at),
                    isoformat_or_none(alert.acked_at),
                ),
            )
            cursor = await conn.execute("SELECT id FROM alerts WHERE normalized_post_id = ?", (normalized_post_id,))
            row = await cursor.fetchone()
            await conn.commit()
        return int(row["id"])

    async def save_event_vote(self, normalized_post_id: int, vote: EventFeedbackVote | None) -> EventVoteRecord | None:
        updated_at = utc_now()
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT id FROM normalized_posts WHERE id = ?", (normalized_post_id,))
            if await cursor.fetchone() is None:
                return None
            if vote is None:
                await conn.execute("DELETE FROM event_feedback_votes WHERE normalized_post_id = ?", (normalized_post_id,))
            else:
                await conn.execute(
                    """
                    INSERT INTO event_feedback_votes (normalized_post_id, vote, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(normalized_post_id) DO UPDATE SET
                        vote = excluded.vote,
                        updated_at = excluded.updated_at
                    """,
                    (normalized_post_id, vote.value, updated_at.isoformat()),
                )
            await conn.commit()
        return EventVoteRecord(normalized_post_id=normalized_post_id, vote=vote, updated_at=updated_at)

    async def update_latency_stage(self, normalized_post_id: int, **timestamps: datetime | None) -> None:
        if not timestamps:
            return
        assignments = ", ".join(f"{key} = ?" for key in timestamps)
        params = [isoformat_or_none(value) for value in timestamps.values()]
        params.append(utc_now().isoformat())
        params.append(normalized_post_id)
        async with self.connection() as conn:
            await conn.execute(
                f"UPDATE latency_samples SET {assignments}, updated_at = ? WHERE normalized_post_id = ?",
                params,
            )
            await conn.commit()

    async def recent_duplicate_candidates(self, entity_key: str, *, within_minutes: int) -> list[DuplicateCandidate]:
        cutoff = (utc_now() - timedelta(minutes=within_minutes)).isoformat()
        query = """
            SELECT alerts.id, normalized_posts.text, analyses.total_score, accounts.authority_rank
            FROM alerts
            JOIN analyses ON analyses.id = alerts.analysis_id
            JOIN normalized_posts ON normalized_posts.id = alerts.normalized_post_id
            JOIN accounts ON accounts.id = normalized_posts.account_id
            WHERE alerts.status IN ('sent', 'dry_run')
              AND accounts.entity_key = ?
              AND alerts.created_at >= ?
            ORDER BY alerts.created_at DESC
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query, (entity_key, cutoff))
            rows = await cursor.fetchall()
        return [
            DuplicateCandidate(
                alert_id=int(row["id"]),
                text=row["text"],
                total_score=float(row["total_score"]),
                authority_rank=int(row["authority_rank"]),
            )
            for row in rows
        ]

    async def upsert_checkpoint(
        self,
        connector: str,
        account_id: str,
        *,
        last_source_post_id: str | None,
        last_published_at: datetime | None,
        last_observed_at: datetime | None,
        status: str,
        detail: str | None = None,
    ) -> None:
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT INTO connector_checkpoints (
                    connector, account_id, last_source_post_id, last_published_at, last_observed_at, status, detail, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector, account_id) DO UPDATE SET
                    last_source_post_id = excluded.last_source_post_id,
                    last_published_at = excluded.last_published_at,
                    last_observed_at = excluded.last_observed_at,
                    status = excluded.status,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (
                    connector,
                    account_id,
                    last_source_post_id,
                    isoformat_or_none(last_published_at),
                    isoformat_or_none(last_observed_at),
                    status,
                    detail,
                    utc_now().isoformat(),
                ),
            )
            await conn.commit()

    async def get_checkpoint(self, connector: str, account_id: str) -> dict[str, Any] | None:
        async with self.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM connector_checkpoints WHERE connector = ? AND account_id = ?",
                (connector, account_id),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def recent_posts(self, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT normalized_posts.*, analyses.total_score, analyses.summary, analyses.categories_json, alerts.status AS alert_status
            FROM normalized_posts
            LEFT JOIN analyses ON analyses.normalized_post_id = normalized_posts.id
            LEFT JOIN alerts ON alerts.normalized_post_id = normalized_posts.id
            ORDER BY normalized_posts.published_at DESC
            LIMIT ?
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query, (limit,))
            rows = await cursor.fetchall()
        return [self._row_to_event_post(row) for row in rows]

    async def recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT alerts.*, normalized_posts.source, normalized_posts.handle, normalized_posts.display_name, analyses.total_score, analyses.summary
            FROM alerts
            JOIN normalized_posts ON normalized_posts.id = alerts.normalized_post_id
            JOIN analyses ON analyses.id = alerts.analysis_id
            ORDER BY alerts.created_at DESC
            LIMIT ?
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query, (limit,))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def recent_events(
        self,
        limit: int = 50,
        *,
        source: SourcePlatform | None = None,
        alert_status: str | None = None,
        decision: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source:
            clauses.append("normalized_posts.source = ?")
            params.append(source.value)
        if alert_status:
            clauses.append("COALESCE(alerts.status, '') = ?")
            params.append(alert_status)
        if decision:
            clauses.append("COALESCE(analyses.decision, '') = ?")
            params.append(decision)
        if query:
            clauses.append(
                "(LOWER(normalized_posts.display_name) LIKE ? OR LOWER(normalized_posts.handle) LIKE ? OR "
                "LOWER(normalized_posts.text) LIKE ? OR LOWER(COALESCE(analyses.summary, '')) LIKE ?)"
            )
            query_value = f"%{query.lower()}%"
            params.extend([query_value, query_value, query_value, query_value])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = """
            SELECT
                normalized_posts.*,
                analyses.id AS analysis_id,
                analyses.summary,
                analyses.categories_json,
                analyses.total_score,
                analyses.decision,
                analyses.reasoning,
                analyses.market_impacts_json,
                analyses.request_cost_usd,
                alerts.id AS alert_id,
                alerts.status AS alert_status,
                alerts.suppression_reason,
                event_feedback_votes.vote AS feedback_vote,
                event_feedback_votes.updated_at AS feedback_vote_updated_at
            FROM normalized_posts
            LEFT JOIN analyses ON analyses.normalized_post_id = normalized_posts.id
            LEFT JOIN alerts ON alerts.normalized_post_id = normalized_posts.id
            LEFT JOIN event_feedback_votes ON event_feedback_votes.normalized_post_id = normalized_posts.id
            {where}
            ORDER BY normalized_posts.observed_at DESC
            LIMIT ?
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query.format(where=where), (*params, limit))
            rows = await cursor.fetchall()
        return [self._row_to_recent_event(row) for row in rows]

    async def get_event(self, normalized_post_id: int) -> dict[str, Any] | None:
        query = """
            SELECT
                normalized_posts.*,
                analyses.id AS analysis_id,
                analyses.model,
                analyses.summary,
                analyses.categories_json,
                analyses.reasoning,
                analyses.market_impacts_json,
                analyses.actor_importance,
                analyses.event_severity,
                analyses.immediacy,
                analyses.novelty,
                analyses.wider_impact,
                analyses.total_score,
                analyses.threshold,
                analyses.decision,
                analyses.input_tokens,
                analyses.output_tokens,
                analyses.cached_input_tokens,
                analyses.request_cost_usd,
                analyses.created_at AS analyzed_at,
                alerts.id AS alert_id,
                alerts.status AS alert_status,
                alerts.message_text AS alert_message_text,
                alerts.suppression_reason,
                alerts.relay_response_json,
                alerts.created_at AS alert_created_at,
                alerts.sent_at,
                alerts.acked_at,
                event_feedback_votes.vote AS feedback_vote,
                event_feedback_votes.updated_at AS feedback_vote_updated_at,
                latency_samples.persisted_at,
                latency_samples.classification_started_at,
                latency_samples.classification_finished_at,
                latency_samples.relay_sent_at,
                latency_samples.relay_acked_at
            FROM normalized_posts
            LEFT JOIN analyses ON analyses.normalized_post_id = normalized_posts.id
            LEFT JOIN alerts ON alerts.normalized_post_id = normalized_posts.id
            LEFT JOIN event_feedback_votes ON event_feedback_votes.normalized_post_id = normalized_posts.id
            LEFT JOIN latency_samples ON latency_samples.normalized_post_id = normalized_posts.id
            WHERE normalized_posts.id = ?
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query, (normalized_post_id,))
            row = await cursor.fetchone()
        return self._row_to_event_detail(row) if row else None

    async def get_canonical_post(self, normalized_post_id: int) -> CanonicalPost | None:
        query = """
            SELECT normalized_posts.*, raw_posts.payload_json
            FROM normalized_posts
            JOIN raw_posts ON raw_posts.id = normalized_posts.raw_post_id
            WHERE normalized_posts.id = ?
        """
        async with self.connection() as conn:
            cursor = await conn.execute(query, (normalized_post_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return CanonicalPost(
            source=SourcePlatform(row["source"]),
            account_db_id=row["account_id"],
            source_account_id=row["source_account_id"],
            display_name=row["display_name"],
            handle=row["handle"],
            source_post_id=row["source_post_id"],
            canonical_url=row["canonical_url"],
            text=row["text"],
            links=json_loads(row["links_json"], []),
            media_urls=json_loads(row["media_urls_json"], []),
            is_reply=bool(row["is_reply"]),
            is_repost=bool(row["is_repost"]),
            published_at=parse_datetime(row["published_at"]) or utc_now(),
            observed_at=parse_datetime(row["observed_at"]) or utc_now(),
            raw_payload=json_loads(row["payload_json"], {}),
            collector_metadata=json_loads(row["collector_metadata_json"], {}),
        )

    async def delete_event(self, normalized_post_id: int) -> bool:
        async with self.connection() as conn:
            cursor = await conn.execute(
                "SELECT raw_post_id FROM normalized_posts WHERE id = ?",
                (normalized_post_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            raw_post_id = int(row["raw_post_id"])
            await conn.execute("DELETE FROM event_feedback_votes WHERE normalized_post_id = ?", (normalized_post_id,))
            await conn.execute("DELETE FROM alerts WHERE normalized_post_id = ?", (normalized_post_id,))
            await conn.execute("DELETE FROM analyses WHERE normalized_post_id = ?", (normalized_post_id,))
            await conn.execute("DELETE FROM latency_samples WHERE normalized_post_id = ?", (normalized_post_id,))
            await conn.execute("DELETE FROM normalized_posts WHERE id = ?", (normalized_post_id,))
            await conn.execute("DELETE FROM raw_posts WHERE id = ?", (raw_post_id,))
            await conn.commit()
        return True

    async def clear_activity(self, *, levels: tuple[str, ...] | None = None) -> int:
        async with self.connection() as conn:
            if levels:
                placeholders = ", ".join("?" for _ in levels)
                cursor = await conn.execute(
                    f"SELECT COUNT(*) AS c FROM activity_log WHERE level IN ({placeholders})",
                    levels,
                )
                row = await cursor.fetchone()
                deleted = int(row["c"] or 0)
                await conn.execute(
                    f"DELETE FROM activity_log WHERE level IN ({placeholders})",
                    levels,
                )
            else:
                cursor = await conn.execute("SELECT COUNT(*) AS c FROM activity_log")
                row = await cursor.fetchone()
                deleted = int(row["c"] or 0)
                await conn.execute("DELETE FROM activity_log")
            await conn.commit()
        return deleted

    async def reset_latency_samples(self) -> int:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) AS c FROM latency_samples")
            row = await cursor.fetchone()
            deleted = int(row["c"] or 0)
            await conn.execute("DELETE FROM latency_samples")
            await conn.commit()
        return deleted

    async def latency_metrics(self) -> dict[str, Any]:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM latency_samples ORDER BY updated_at DESC LIMIT 500")
            rows = await cursor.fetchall()
        metrics: dict[str, list[float]] = {
            "source_to_observed_seconds": [],
            "observed_to_persisted_seconds": [],
            "persisted_to_classification_seconds": [],
            "classification_to_relay_seconds": [],
            "end_to_end_seconds": [],
        }
        for row in rows:
            published_at = parse_datetime(row["source_published_at"])
            observed_at = parse_datetime(row["observed_at"])
            persisted_at = parse_datetime(row["persisted_at"])
            classification_finished_at = parse_datetime(row["classification_finished_at"])
            relay_acked_at = parse_datetime(row["relay_acked_at"])
            classification_started_at = parse_datetime(row["classification_started_at"])
            relay_sent_at = parse_datetime(row["relay_sent_at"])
            if published_at and observed_at:
                metrics["source_to_observed_seconds"].append((observed_at - published_at).total_seconds())
            if observed_at and persisted_at:
                metrics["observed_to_persisted_seconds"].append((persisted_at - observed_at).total_seconds())
            if persisted_at and classification_finished_at:
                metrics["persisted_to_classification_seconds"].append(
                    (classification_finished_at - persisted_at).total_seconds()
                )
            if classification_finished_at and relay_acked_at:
                metrics["classification_to_relay_seconds"].append((relay_acked_at - classification_finished_at).total_seconds())
            if published_at and relay_acked_at:
                metrics["end_to_end_seconds"].append((relay_acked_at - published_at).total_seconds())
            if classification_started_at and relay_sent_at:
                pass
        return {name: summarize_distribution(values) for name, values in metrics.items()}

    async def usage_summary(self, *, since: datetime | None = None) -> dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS analysis_count,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                COALESCE(SUM(request_cost_usd), 0) AS request_cost_usd,
                MIN(created_at) AS first_analysis_at,
                MAX(created_at) AS last_analysis_at
            FROM analyses
        """
        params: tuple[Any, ...] = ()
        if since is not None:
            query += " WHERE created_at >= ?"
            params = (since.isoformat(),)
        async with self.connection() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
        return dict(row)

    async def record_api_request(
        self,
        *,
        provider: str,
        endpoint: str,
        method: str,
        request_kind: str,
        status_code: int | None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        created = created_at or utc_now()
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT INTO api_request_log (
                    provider, endpoint, method, request_kind, status_code, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    endpoint,
                    method,
                    request_kind,
                    status_code,
                    json_dumps(metadata or {}),
                    created.isoformat(),
                ),
            )
            await conn.commit()

    async def api_request_summary(
        self,
        *,
        provider: str,
        request_kind: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS request_count,
                COALESCE(SUM(CASE WHEN status_code BETWEEN 200 AND 299 THEN 1 ELSE 0 END), 0) AS successful_request_count,
                MIN(created_at) AS first_request_at,
                MAX(created_at) AS last_request_at
            FROM api_request_log
            WHERE provider = ?
        """
        params: list[Any] = [provider]
        if request_kind is not None:
            query += " AND request_kind = ?"
            params.append(request_kind)
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        async with self.connection() as conn:
            cursor = await conn.execute(query, tuple(params))
            row = await cursor.fetchone()
        return dict(row)

    async def add_activity(self, record: ActivityRecord) -> ActivityRecord:
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT INTO activity_log (kind, level, component, title, message, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.kind,
                    record.level,
                    record.component,
                    record.title,
                    record.message,
                    json_dumps(record.metadata),
                    record.created_at.isoformat(),
                ),
            )
            cursor = await conn.execute("SELECT last_insert_rowid() AS id")
            row = await cursor.fetchone()
            await conn.commit()
        return record.model_copy(update={"id": int(row["id"])})

    async def recent_activity(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "level": row["level"],
                "component": row["component"],
                "title": row["title"],
                "message": row["message"],
                "metadata": json_loads(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def count_posts(self) -> int:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) AS c FROM normalized_posts")
            row = await cursor.fetchone()
        return int(row["c"])

    async def count_alerts(self) -> int:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) AS c FROM alerts WHERE status IN ('sent', 'dry_run')")
            row = await cursor.fetchone()
        return int(row["c"])

    async def connector_checkpoint_snapshot(self) -> list[dict[str, Any]]:
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM connector_checkpoints ORDER BY connector, account_id")
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _insert_account(self, conn: aiosqlite.Connection, account: AccountConfig) -> None:
        await conn.execute(
            """
            INSERT INTO accounts (
                id, source, entity_key, display_name, handle, source_account_id, source_url, official, active,
                authority_rank, alert_threshold, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.id,
                account.source.value,
                account.entity_key,
                account.display_name,
                account.handle,
                account.source_account_id,
                account.source_url,
                1 if account.official else 0,
                1 if account.active else 0,
                account.authority_rank,
                account.alert_threshold,
                json_dumps(account.metadata),
                account.created_at.isoformat(),
                account.updated_at.isoformat(),
            ),
        )

    def _row_to_account(self, row: aiosqlite.Row) -> AccountConfig:
        return AccountConfig(
            id=row["id"],
            source=SourcePlatform(row["source"]),
            entity_key=row["entity_key"],
            display_name=row["display_name"],
            handle=row["handle"],
            source_account_id=row["source_account_id"],
            source_url=row["source_url"],
            official=bool(row["official"]),
            active=bool(row["active"]),
            authority_rank=int(row["authority_rank"]),
            alert_threshold=row["alert_threshold"],
            metadata=json_loads(row["metadata_json"], {}),
            created_at=parse_datetime(row["created_at"]) or utc_now(),
            updated_at=parse_datetime(row["updated_at"]) or utc_now(),
        )

    @staticmethod
    def _row_to_event_post(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source": row["source"],
            "handle": row["handle"],
            "display_name": row["display_name"],
            "source_post_id": row["source_post_id"],
            "text": row["text"],
            "canonical_url": row["canonical_url"],
            "published_at": row["published_at"],
            "observed_at": row["observed_at"],
            "categories": json_loads(row["categories_json"], []),
            "summary": row["summary"],
            "total_score": row["total_score"],
            "alert_status": row["alert_status"],
        }

    @staticmethod
    def _row_to_recent_event(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "normalized_post_id": row["id"],
            "source": row["source"],
            "handle": row["handle"],
            "display_name": row["display_name"],
            "source_post_id": row["source_post_id"],
            "canonical_url": row["canonical_url"],
            "text": row["text"],
            "published_at": row["published_at"],
            "observed_at": row["observed_at"],
            "summary": row["summary"],
            "categories": json_loads(row["categories_json"], []),
            "total_score": row["total_score"],
            "decision": row["decision"],
            "reasoning": row["reasoning"],
            "market_impacts": Repository._parse_market_impacts(row["market_impacts_json"]),
            "request_cost_usd": row["request_cost_usd"],
            "alert_id": row["alert_id"],
            "alert_status": row["alert_status"],
            "suppression_reason": row["suppression_reason"],
            "feedback_vote": row["feedback_vote"],
            "feedback_vote_updated_at": row["feedback_vote_updated_at"],
        }

    @staticmethod
    def _row_to_event_detail(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "normalized_post_id": row["id"],
            "source": row["source"],
            "account_id": row["account_id"],
            "source_account_id": row["source_account_id"],
            "handle": row["handle"],
            "display_name": row["display_name"],
            "source_post_id": row["source_post_id"],
            "canonical_url": row["canonical_url"],
            "text": row["text"],
            "links": json_loads(row["links_json"], []),
            "media_urls": json_loads(row["media_urls_json"], []),
            "is_reply": bool(row["is_reply"]),
            "is_repost": bool(row["is_repost"]),
            "published_at": row["published_at"],
            "observed_at": row["observed_at"],
            "analysis": {
                "id": row["analysis_id"],
                "model": row["model"],
                "summary": row["summary"],
                "categories": json_loads(row["categories_json"], []),
                "reasoning": row["reasoning"],
                "market_impacts": Repository._parse_market_impacts(row["market_impacts_json"]),
                "breakdown": (
                    {
                        "actor_importance": row["actor_importance"],
                        "event_severity": row["event_severity"],
                        "immediacy": row["immediacy"],
                        "novelty": row["novelty"],
                        "wider_impact": row["wider_impact"],
                    }
                    if row["analysis_id"] is not None
                    else None
                ),
                "total_score": row["total_score"],
                "threshold": row["threshold"],
                "decision": row["decision"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "request_cost_usd": row["request_cost_usd"],
                "created_at": row["analyzed_at"],
            },
            "alert": {
                "id": row["alert_id"],
                "status": row["alert_status"],
                "message_text": row["alert_message_text"],
                "suppression_reason": row["suppression_reason"],
                "relay_response": json_loads(row["relay_response_json"], {}),
                "created_at": row["alert_created_at"],
                "sent_at": row["sent_at"],
                "acked_at": row["acked_at"],
            }
            if row["alert_id"] is not None
            else None,
            "feedback_vote": row["feedback_vote"],
            "feedback_vote_updated_at": row["feedback_vote_updated_at"],
            "latency": {
                "persisted_at": row["persisted_at"],
                "classification_started_at": row["classification_started_at"],
                "classification_finished_at": row["classification_finished_at"],
                "relay_sent_at": row["relay_sent_at"],
                "relay_acked_at": row["relay_acked_at"],
            },
        }

    @staticmethod
    def _parse_market_impacts(raw_value: str | None) -> dict[str, Any]:
        try:
            parsed = json_loads(raw_value, {})
            return MarketImpactSnapshot.model_validate(parsed).model_dump(mode="json")
        except Exception:  # noqa: BLE001
            return MarketImpactSnapshot.flat().model_dump(mode="json")


def summarize_distribution(values: Iterable[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "min": None, "max": None}
    return {
        "count": len(ordered),
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "p99": percentile(ordered, 99),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def percentile(values: list[float], pct: int) -> float:
    if not values:
        raise ValueError("percentile requires values")
    if len(values) == 1:
        return round(values[0], 3)
    rank = (pct / 100) * (len(values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(values[lower], 3)
    weight = rank - lower
    interpolated = values[lower] + (values[upper] - values[lower]) * weight
    return round(interpolated, 3)
