# Troubleshooting

This guide records failure modes that are represented in the codebase or development history. It intentionally avoids hypothetical problems that have not been observed or implemented.

## The root page says "Frontend build missing"

FastAPI returns a 503 fallback page when `event_radar/static/app/index.html` is absent.

Fix:

```bash
cd frontend
npm ci
npm run build
cd ..
```

Then restart Event Radar.

## Startup fails with `event_radar_instance_running`

Event Radar uses a database-scoped single-instance lock. Another Event Radar process is already using the same deployment database, or a previous process has not released the lock yet.

Fix: stop the other Event Radar instance cleanly. If two independent instances are intentional, give them separate `EVENT_RADAR_DATABASE_PATH` values. Do not bypass the lock while sharing one SQLite database.

## Port 8089 is already in use

The Bash launcher checks the listener on the configured port. It only terminates a stale process when the process command identifies it as Event Radar; it refuses to kill an unrelated service.

Fix: stop the unrelated listener yourself or choose another `EVENT_RADAR_APP_PORT` and corresponding URL.

## X stream reports rate limiting / reduced freshness

The connector handles X `429 Too Many Requests` responses by recording a rate-limit state and backing off. Sustained rate limits reduce stream freshness.

Fix: allow the backoff to run, review your X API plan/usage, and avoid repeatedly restarting the connector to defeat the backoff.

## Truth Social direct collection is blocked

Development history records direct Truth Social requests being blocked in some environments. The connector can switch to browser-backed collection.

Check that:

1. `frontend/node_modules` exists (`cd frontend && npm ci`).
2. Playwright browsers are installed (`npx playwright install`).
3. A valid `EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE` or `EVENT_RADAR_TRUTH_SOCIAL_COOKIE` is configured.
4. The cookie state belongs to the operator and is permitted for the intended use.

The connector also handles Truth Social rate limits with bounded backoff; wait for the retry window rather than creating a tight polling loop.

## Playwright browser worker cannot start

The Truth Social worker loads Playwright from `frontend/node_modules` and starts Chromium. Missing Node dependencies or browser binaries will prevent that path from working.

Fix:

```bash
cd frontend
npm ci
npx playwright install
```

If a Linux browser still cannot start, install the platform libraries Playwright reports as missing. The repository does not pin a Linux distribution, so no universal OS package command is documented here.

## OpenAI classification returns incomplete structured output

The classifier uses the Responses API with strict structured output. The code retries incomplete JSON once with a larger output budget. If classification is still unavailable, Event Radar records a classification failure rather than substituting a heuristic score.

Check the configured API key, model access, provider response, and local activity/logs. Manual reprocessing is available through the event refresh path/dashboard after the provider issue is resolved.

## Events are stored but no relay message is sent

The relay client suppresses delivery when required relay configuration is missing, and it deliberately returns dry-run results when `EVENT_RADAR_ALERT_DRY_RUN` is enabled.

Check:

- `EVENT_RADAR_ALERT_DRY_RUN`.
- `EVENT_RADAR_TELEGRAM_RELAY_BASE_URL`.
- `EVENT_RADAR_TELEGRAM_RELAY_API_KEY`.
- `EVENT_RADAR_TELEGRAM_RELAY_CHAT_ID`.
- The alert's threshold/deduplication/suppression state in the dashboard.

Event Radar expects an HTTP relay with a compatible `/v1/messages` endpoint; it is not a direct Telegram Bot API client.

## Official OpenAI billed spend is unavailable or zero

The dashboard can attempt best-effort official project cost lookup when an administrative key/project configuration is present. Development history records cases where the provider could not cleanly attribute runtime activity to the configured project.

The service therefore keeps persisted Event Radar analysis usage/tracked spend as the local workload metric and can mark official billed spend unavailable instead of presenting a misleading zero.

## Frontend tests cannot start their backend

The Playwright configuration starts a local Uvicorn test server on `127.0.0.1:8092` with collectors disabled and a test database under `var/`. Ensure the Python virtual environment exists and project dependencies are installed before running `npm run e2e`.

## Configuration file is not being read

The public-ready default is project-local `config/env.sh`. You can override it with `EVENT_RADAR_ENV_FILE`.

Start from `config/env.example`. The parser retains compatibility with some historical environment-variable aliases, but new installations should use the documented `EVENT_RADAR_*` names.
