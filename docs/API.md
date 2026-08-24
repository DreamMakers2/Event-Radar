# API Reference

Event Radar exposes a local FastAPI application. The default base URL is `http://127.0.0.1:8089`.

FastAPI generates the authoritative schema at `/openapi.json` and interactive documentation at `/docs`. This file provides a stable overview of the routes implemented in `event_radar/main.py`.

## Security warning

The API does not implement user authentication or authorization. Keep the default loopback binding or place any remote deployment behind an independently configured authenticated access layer.

## Health and overview

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Service, database, and connector-oriented health state |
| GET | `/api/v1/overview` | Combined health, connectors, accounts, alerts, posts, activity, latency, and cost data |
| GET | `/api/v1/dashboard` | Dashboard-oriented aggregate payload |

## Events and posts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/posts?limit=50` | Recent normalized posts |
| GET | `/api/v1/events` | Filtered event list |
| GET | `/api/v1/events/{normalized_post_id}` | Event detail |
| POST | `/api/v1/events/test-trigger` | Run the tracked-handle manual test path |
| POST | `/api/v1/events/{normalized_post_id}/refresh` | Re-run processing for an existing event |
| PATCH | `/api/v1/events/{normalized_post_id}/vote` | Set or clear persisted feedback |
| DELETE | `/api/v1/events/{normalized_post_id}` | Delete an event and its associated persisted state according to repository logic |
| GET | `/api/v1/events/stream` | Server-Sent Events stream for live UI updates |

`GET /api/v1/events` accepts these query parameters:

- `limit`: 1–100, default 50.
- `source`: a supported `SourcePlatform` value such as `x` or `truth_social`.
- `alert_status`: optional alert-status filter.
- `decision`: optional decision filter.
- `q`: optional text search, up to 120 characters.

Use `/openapi.json` for the exact request/response schemas of manual trigger and feedback payloads.

## Alerts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/alerts?limit=50` | Recent alert records |

## Tracked accounts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/accounts` | List tracked accounts |
| POST | `/api/v1/accounts` | Create a tracked account |
| PATCH | `/api/v1/accounts/{account_id}` | Update a tracked account |
| DELETE | `/api/v1/accounts/{account_id}` | Remove a tracked account |

Account uniqueness/conflict errors are returned as HTTP 409 by the FastAPI exception handler. Missing account/event identifiers return HTTP 404 where implemented.

## Connectors

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/connectors` | Current connector status snapshots |

## Activity and latency

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/activity?limit=100` | Recent activity; limit is 1–200 |
| DELETE | `/api/v1/activity` | Clear recent activity records |
| DELETE | `/api/v1/activity/attention` | Clear attention-category activity |
| GET | `/api/v1/metrics/latency` | Aggregated latency metrics |
| DELETE | `/api/v1/metrics/latency` | Clear latency records |

## SSE stream

`GET /api/v1/events/stream` returns `text/event-stream`. Messages are serialized as JSON in SSE `data:` records. Current stream message types are defined by the backend event bus and mirrored by the frontend TypeScript types; consumers should tolerate additive fields and unknown future event types.

## Response hardening

The application middleware sets a same-origin Content Security Policy, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and `X-Content-Type-Options: nosniff`. These headers protect the bundled local dashboard but do not replace authentication or transport security for a remote deployment.

## Error behavior

- Unhandled application exceptions are converted to HTTP 500 with `{"detail":"internal_server_error"}` while the detailed error is recorded in local activity/logging.
- Classification unavailability is exposed as HTTP 503 for request paths that propagate `ClassificationUnavailableError`.
- Repository account conflicts return HTTP 409.

Do not build clients around undocumented internal fields when the generated OpenAPI schema provides a typed contract.
