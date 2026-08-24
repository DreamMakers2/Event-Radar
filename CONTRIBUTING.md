# Contributing to Event Radar

Contributions are welcome when they keep the project secure, reviewable, and consistent with the documented architecture.

## Development setup

Follow [docs/SETUP.md](docs/SETUP.md) and [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md). Use project-local configuration; never commit credentials, cookies, databases, logs, private endpoints, machine-specific paths, or generated test artifacts.

## Before opening a pull request

Run the checks that apply to your change:

```bash
pytest
cd frontend
npm test
npm run build
npm run lint
npm run e2e
npm audit --omit=dev
```

Browser tests require Playwright browser binaries. See `docs/SETUP.md` for installation.

## Pull request expectations

- Keep changes focused and explain the behavior being changed.
- Add or update tests when behavior changes.
- Update documentation when configuration, commands, APIs, or architecture change.
- Preserve the default loopback-only posture unless a security-reviewed deployment change explicitly requires otherwise.
- Use placeholders in examples. Do not include real tokens, cookies, email addresses, private hosts, internal DNS names, identifying filesystem paths, or production data.
- Do not weaken error handling or convert classification failures into unverified local scores without documenting and reviewing the change.

## Licensing

By intentionally submitting a contribution for inclusion in Event Radar, you agree that it may be distributed under the repository's combined Apache License 2.0 + Commons Clause License Condition v1.0 terms in `LICENSE`.

## Security issues

Do not disclose suspected vulnerabilities in a public issue. Follow [SECURITY.md](SECURITY.md).
