# Public Release Checklist

This checklist documents the repository state prepared for final maintainer review. Repository visibility is intentionally outside the scope of the automated cleanup and must remain a deliberate maintainer action.

## Source and privacy

- [x] Remove internal operational-memory documentation from the retained tree.
- [x] Replace machine-specific root-owned configuration paths with project-local configuration.
- [x] Replace the deployment-specific private relay address with a loopback placeholder/default.
- [x] Remove the legacy launcher that encoded an operator-specific filesystem location and standardize the Windows launcher on the project-relative PowerShell implementation.
- [x] Remove the Playwright root-home override from the public configuration.
- [x] Expand `.gitignore` for environment files, credentials/key material, databases, logs, browser/test artifacts, and editor/OS noise.
- [x] Provide a sanitized `config/env.example` containing placeholders only.
- [x] Remove sensitive/environment-specific material from the retained `main` history rather than only deleting it in a later snapshot.
- [x] Do not create a backup branch/tag that intentionally preserves the pre-sanitization history.

## Documentation and legal

- [x] Add `LICENSE` with Apache License 2.0 subject to Commons Clause License Condition v1.0.
- [x] Add `NOTICE`.
- [x] Add contribution and security policies.
- [x] Add step-by-step setup instructions.
- [x] Separate verified requirements from unknown/unverified hardware and software claims.
- [x] Add architecture documentation, GitHub-native Mermaid, and an SVG architecture infographic.
- [x] Add API and evidence-based troubleshooting documentation.
- [x] Rewrite the README as the project entry point with restrained badges and documentation links.

## Security posture

- [x] Keep the default FastAPI bind address on loopback.
- [x] Document that the API has no built-in user authentication/authorization.
- [x] Document external-service and credential trust boundaries.
- [x] Default the example installation to relay dry-run mode.
- [x] Avoid embedding credentials, cookies, chat IDs, private hosts, internal DNS names, or identifying paths in examples.

## Maintainer checks before changing visibility

- [ ] Review the final commit and rendered README/diagram on GitHub.
- [x] Confirm repository visibility remains private and unchanged by sanitation.
- [x] Review GitHub-hosted objects outside the Git tree. At verification time there were no tags, releases, Actions workflows/runs/artifacts/caches, repository environments, repository/Dependabot/Codespaces secrets, repository variables, issues, pull requests, or issue/PR attachments.
- [x] Confirm `main` is the default branch and record that it is currently unprotected. Branch protection and repository rulesets are unavailable for this private repository on the current GitHub plan and must be reconsidered before or when publication makes them available.
- [ ] Enable the desired private vulnerability-reporting/security-advisory workflow if it is not already configured.
- [ ] Perform the final human review before making any visibility change.

## Release terminology

The Apache 2.0 + Commons Clause combination is **source-available**, not OSI-approved open source. Public descriptions should not label the project "open source" unless the licensing terms change.
