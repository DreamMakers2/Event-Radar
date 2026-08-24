# Security Policy

## Security model

Event Radar is designed as a local-first operator service. Its default application host is `127.0.0.1`, and the FastAPI routes do **not** implement user authentication or authorization. Treat loopback binding as an important security boundary.

Do not expose the service directly to an untrusted LAN or the public Internet. If remote access is required, place it behind an independently configured reverse proxy or access gateway that provides TLS, authentication, authorization, and appropriate network controls.

## Secrets and sensitive state

Keep the following outside Git:

- OpenAI API/admin keys.
- X bearer tokens.
- Truth Social cookies or cookie files.
- Telegram relay API keys and chat identifiers.
- Runtime SQLite databases and WAL/SHM files.
- Logs, Playwright traces, browser state, and environment-specific configuration.

`config/env.sh` is ignored by Git. Start from `config/env.example`, keep the real file local, and restrict its filesystem permissions appropriately for your operating system.

## External services

The application can send data to configured external services, including OpenAI for classification, X and Truth Social for source ingestion, the European Central Bank endpoint used for FX reference data, and a configured Telegram relay. Review the code and the applicable provider policies before processing sensitive content.

## Reporting a vulnerability

Do not include exploit details, credentials, private URLs, or sensitive logs in a public issue.

Use the repository's private vulnerability-reporting/security-advisory channel if GitHub presents one. If no private channel is available, open a minimal issue that asks maintainers to establish a private contact path, without disclosing the vulnerability itself.

A useful private report includes the affected revision, impact, reproduction conditions, and a minimal proof of concept with all credentials and private identifiers removed.

## Supported versions

This repository does not currently publish multiple maintained release lines. Security fixes are expected to target the current default branch unless maintainers state otherwise.
