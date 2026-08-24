# Event Radar Frontend

This package contains the React + TypeScript + Vite operator dashboard that is built into static assets and served by the FastAPI backend.

## What It Includes

- Queue-first event triage surface with filterable live events
- On-demand inspector drawer for detailed scoring, timing, and relay outcome
- Compact operational panels for connector health, warnings, activity, latency, cost, and tracked accounts
- Grouped tracked-account management with inline threshold editing plus pause, resume, and remove controls
- Vitest unit coverage and Playwright viewport coverage for desktop, tablet, and mobile layouts

## Local Development

Install dependencies:

```bash
npm install
```

Run the Vite dev server:

```bash
npm run dev
```

Build the production bundle served by FastAPI:

```bash
npm run build
```

## Validation

- Lint: `npm run lint`
- Unit tests: `npm run test -- --run`
- Browser coverage: `npm run e2e`

## Notes

- Production builds write static assets into `../event_radar/static/app/`
- The browser test suite covers the target desktop resolutions `1728x827`, `2304x1151`, and `3096x1151`, plus tablet and mobile
- The frontend expects the backend account API to support `GET`, `POST`, `PATCH`, and `DELETE` on `/api/v1/accounts`
