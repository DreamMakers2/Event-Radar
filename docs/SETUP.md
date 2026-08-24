# Setup Guide

This guide sets up Event Radar as a new, independent installation. It uses only project-local paths and placeholder configuration.

## 1. Check the requirements

Read [REQUIREMENTS.md](REQUIREMENTS.md) first. The backend requires Python 3.12 or newer. The frontend build and Truth Social browser fallback require Node.js/npm and the packages locked in `frontend/package-lock.json`.

## 2. Clone the repository

```bash
git clone <your-repository-url>
cd Event-Radar
```

The directory name is not significant. Do not copy another operator's runtime database, cookies, environment file, logs, or browser state into a new installation.

Run the documented commands from the repository root unless a step explicitly changes directory. The default environment-file and database paths are relative paths, so changing the working directory changes where those defaults resolve.

## 3. Create the Python environment

### Bash environment (Linux/WSL-style setup)

The repository includes a Bash launcher for Linux/WSL-style environments, but it does not preserve an exact tested distribution/version.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If `py` is unavailable, use a Python 3.12+ `python` executable instead.

Other operating systems may be able to use the same Python/Node workflow, but the repository does not contain evidence for an additional OS compatibility claim.

## 4. Install the frontend dependencies

Use the committed npm lockfile for reproducibility:

```bash
cd frontend
npm ci
cd ..
```

Event Radar's Truth Social browser worker imports Playwright from `frontend/node_modules`, so frontend dependencies are also runtime dependencies when browser-backed Truth Social collection is needed.

For browser-backed collection and browser tests, install the Playwright browsers:

```bash
cd frontend
npx playwright install
cd ..
```

On Linux, Playwright may additionally require operating-system libraries. Follow Playwright's platform-specific installation instructions if the browser cannot launch; the repository does not pin a Linux distribution or an OS package list.

## 5. Create private configuration

Copy the example file:

```bash
mkdir -p config
cp config/env.example config/env.sh
```

On Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force config | Out-Null
Copy-Item config\env.example config\env.sh
```

`config/env.sh` is ignored by Git. Edit it locally and replace only the values you actually use.

### OpenAI

Set `EVENT_RADAR_OPENAI_API_KEY` for model classification. Without a usable key, Event Radar persists the post and records a classification failure rather than manufacturing a heuristic score.

`EVENT_RADAR_OPENAI_ADMIN_KEY` is optional and is used only for best-effort official organization/project cost visibility. The local analysis records remain the service's own workload record.

### X

Set `EVENT_RADAR_X_BEARER_TOKEN` to enable the official X connector. The code supports a filtered stream plus catch-up polling and handles rate-limit responses with backoff.

### Truth Social

Provide either:

- `EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE` pointing to a local cookie file, or
- `EVENT_RADAR_TRUTH_SOCIAL_COOKIE` containing an authenticated cookie header.

Truth Social can fall back from direct HTTP collection to a Playwright/Chromium-backed worker when direct requests are blocked. Keep cookies private and outside the repository.

### Telegram relay

Event Radar does not call Telegram directly. It posts to a separately configured HTTP relay at `EVENT_RADAR_TELEGRAM_RELAY_BASE_URL` using `EVENT_RADAR_TELEGRAM_RELAY_API_KEY` and `EVENT_RADAR_TELEGRAM_RELAY_CHAT_ID`.

The example relay URL is loopback-only. Replace it with your own relay endpoint only after reviewing its security. If the relay key or chat ID is absent, alert delivery is suppressed.

Keep `EVENT_RADAR_ALERT_DRY_RUN='true'` during initial validation.

## 6. Build the dashboard

```bash
cd frontend
npm run build
cd ..
```

Vite writes the production bundle into `event_radar/static/app`, which FastAPI serves at `/` and `/static/app/`.

## 7. Run Event Radar

From the repository root, with the Python environment active:

```bash
event-radar
```

The default UI is:

```text
http://127.0.0.1:8089/
```

Health endpoint:

```text
http://127.0.0.1:8089/healthz
```

FastAPI's generated API documentation is available at `/docs`, and the OpenAPI document is available at `/openapi.json` unless you intentionally change the FastAPI application configuration.

### Linux/WSL launcher

`scripts/start_event_radar.sh` can create/sync the Python environment, install/build the frontend, check the configured port, and start the service. It uses standard shell utilities described in [REQUIREMENTS.md](REQUIREMENTS.md).

### Native Windows launcher

After the frontend has been built, run:

```text
launch_event_radar.bat
```

It invokes `start_event_radar.ps1`, creates or refreshes the project-local Python virtual environment, and starts Uvicorn. The Windows launcher keeps the child process in a Job Object so closing the launcher process also terminates the service it started.

## 8. Validate before enabling delivery

1. Open `/healthz` and confirm the service starts cleanly.
2. Open the dashboard and review connector state.
3. Keep `EVENT_RADAR_ALERT_DRY_RUN='true'` and exercise the manual event test path.
4. Confirm X and/or Truth Social collection only after providing your own credentials.
5. Confirm classification succeeds with your OpenAI configuration.
6. Point the relay at your own endpoint and verify it independently.
7. Only then disable dry-run mode if real alert delivery is intended.

## 9. Run the project checks

Backend:

```bash
pytest
```

Frontend unit tests and production build:

```bash
cd frontend
npm test
npm run lint
npm run build
```

Browser coverage:

```bash
npm run e2e
```

Production dependency audit:

```bash
npm audit --omit=dev
```

## Upgrading an installation

Before pulling changes, back up any runtime database you need to retain and keep private configuration separate from Git. After updating:

```bash
python -m pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
pytest
```

Review configuration and release documentation for newly introduced environment variables before restarting the service.
