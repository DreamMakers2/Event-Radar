# Requirements

This document separates requirements that are directly evidenced by the repository from requirements that cannot be verified from the available source and development history.

## Hardware

### Hardware actually used and verified

The retained repository does **not** record a trustworthy hardware inventory for the machine on which Event Radar was developed or exercised. No exact CPU model, CPU architecture, RAM quantity, storage capacity/type, GPU model, network adapter, or peripheral inventory is preserved in the public-ready source.

Therefore, this project does not claim an exact "verified hardware configuration." Historical machine-specific paths and network identifiers were intentionally removed during public-release sanitization because they identified an operator environment without establishing meaningful compatibility requirements.

### Evidence-based minimum hardware

No evidence-based numeric minimum for CPU cores, RAM, or free storage can be established from the repository. Publishing numbers here would be speculative.

What the code does establish:

- **CPU/architecture:** no CPU architecture is hard-coded. The host architecture must be supported by Python 3.12+, the installed Python packages, Node.js, and Playwright/browser binaries used on that host.
- **RAM:** no fixed amount is encoded or measured. Memory use depends on FastAPI, the SQLite workload, the frontend build, and whether a Playwright browser process is active.
- **Storage:** persistent application state is stored in SQLite under `var/` by default. Additional storage is used by the Python virtual environment, `frontend/node_modules`, Playwright browser binaries, frontend build assets, logs, and test artifacts. The repository contains no measured storage floor.
- **GPU/accelerator:** the application code has no CUDA, ROCm, Metal-compute, or other accelerator dependency. Browser rendering may use platform/browser acceleration, but the project has no verified GPU requirement or GPU compatibility matrix.
- **Networking:** outbound network access is materially required for whichever external connectors/services you enable. See the network table below.
- **Peripherals/interfaces:** the repository does not reference serial ports, GPIO, cameras, microphones, capture cards, USB devices, or other dedicated hardware interfaces.

### Recommended hardware

The repository has no benchmark data from which to derive numeric recommended CPU, RAM, or storage specifications. For a deployment, size the host using observed ingestion rate, browser usage, SQLite growth, test/build workload, and retention needs. Record measured results before publishing a recommendation.

## Network requirements

| Destination | Protocol | Purpose | Required when |
| --- | --- | --- | --- |
| `api.openai.com` by default | HTTPS | Structured event classification; optional official cost data | OpenAI classification/cost features are enabled |
| `api.x.com` by default | HTTPS | X filtered stream, polling, and usage endpoints | X monitoring is enabled |
| `truthsocial.com` by default | HTTPS | Truth Social HTTP/browser-backed collection | Truth Social monitoring is enabled |
| European Central Bank FX endpoint | HTTPS | EUR/USD reference-rate lookup used by cost reporting | Cost conversion refresh is used |
| Operator-configured Telegram relay | HTTP or HTTPS as configured | Alert delivery to the relay | Real relay delivery is enabled |

The FastAPI server binds to `127.0.0.1:8089` by default. No inbound Internet access is required for the default local deployment. The API has no built-in user authentication; do not expose it directly to an untrusted network.

## Software requirements

### Backend

| Component | Repository requirement/evidence |
| --- | --- |
| Python | `>=3.12` in `pyproject.toml` |
| Packaging | `setuptools>=68`, `wheel` build requirements |
| Python package manager | `pip` is used by repository setup/launcher commands |
| SQLite | Used through Python/`aiosqlite`; no external database server is required |
| FastAPI | `>=0.115,<1` |
| Uvicorn | `>=0.30,<1` with standard extras |
| aiosqlite | `>=0.20,<1` |
| httpx | `>=0.27,<1` |
| Pydantic | `>=2.8,<3` |
| Backend tests | pytest `>=9.0.3,<10`, pytest-asyncio `>=1,<2` |

The repository does not pin an exact Python patch version or a particular Python distribution.

### Frontend and browser worker

The frontend uses npm with a lockfile (`lockfileVersion: 3`). The current manifest includes React 19, Vite 8, TypeScript 5.9, Vitest 4, ESLint 9, and Playwright 1.58-era package ranges; the lockfile resolves the actual dependency graph used by `npm ci`.

The repository does **not** record the exact Node.js/npm version used successfully by the original development machine, and it does not declare a top-level `engines.node` requirement. Some locked frontend dependencies require modern Node 20.x/22.x/24.x ranges. Use a Node.js release that satisfies `npm ci` for the committed lockfile; do not treat an undocumented Node patch version as verified.

Truth Social browser-backed collection loads Playwright from `frontend/node_modules` and launches Chromium. Install frontend packages before relying on that fallback, and install the Playwright browser binaries.

### Operating systems

The codebase contains both:

- a native Windows PowerShell launcher (`start_event_radar.ps1` plus `launch_event_radar.bat`), and
- a Bash launcher (`scripts/start_event_radar.sh`) suitable for Linux/WSL-style environments.

The repository does not preserve exact tested Windows, WSL, Linux distribution, kernel, or macOS versions. macOS has no dedicated launcher in the repository; running the generic Python/Node setup manually may work, but no macOS compatibility claim is verified here.

### Shell/external tools

The Bash launcher uses common Unix tools including `bash`, `curl`, `ss`, `ps`, `sed`, `awk`, `find`, `sort`, and standard process/signal utilities. It also expects `python3`, and Node/npm are needed to build the frontend.

The native Windows launcher requires PowerShell and either the `py` launcher or a `python` executable capable of creating a Python 3.12+ virtual environment.

### Drivers and firmware

No project-specific hardware drivers or firmware versions are referenced by the application. Playwright browser execution may require OS-provided browser/runtime libraries; these are platform-specific and are not pinned by this repository.

## External accounts and credentials

Depending on enabled features, an installation needs credentials or session state for:

- OpenAI API classification.
- X official API access.
- Truth Social authenticated session/cookies.
- The operator's Telegram relay.
- Optional OpenAI administrative cost visibility.

No credentials are shipped with the repository. See [SETUP.md](SETUP.md) and `config/env.example`.

## Verification scope

The repository includes backend tests, frontend unit tests, a production frontend build check, Playwright browser tests, and an npm production-dependency audit command. These verify software behavior; they do not establish unsupported hardware minima or an operating-system compatibility matrix.
