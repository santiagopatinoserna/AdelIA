# Security Policy

AdelIA stores personal medical data. Security issues are taken seriously.

## Reporting a vulnerability

**Do not open public Issues for security concerns.** Email **security@godi.ai** with:

- A clear description of the issue
- Steps to reproduce (or proof-of-concept code)
- The affected component (apps/web, apps/api, infra) and AdelIA version (commit SHA or tag)
- Your name and contact details (for acknowledgement, optional)

We aim to acknowledge within 72 hours and provide a remediation plan within 14 days.

## Scope

In scope:

- **Authentication and session handling** — magic-link flow, JWT signing/verification, session lifecycle
- **Cross-user data leakage** — any path that returns another user's document, briefing, or personal data
- **File handling** — upload validation, S3 key sanitization, OCR pipeline
- **Cryptographic key management** — `AUTH_SECRET` handling, BYOK encryption (envelope) for user API keys
- **GDPR compliance** — data export, deletion, audit logging

Out of scope (not vulnerabilities):

- Self-host operator configuring weak secrets — this is the operator's responsibility, see Hardening notes below
- Denial of service from a single account exceeding rate limits — design choice for v0.1
- Social engineering against operators or end users

## Disclosure

After a fix is published, we will publicly disclose the vulnerability with credit to the reporter (unless anonymity was requested). Coordinated disclosure timeline: typically 90 days from initial report or sooner if the fix is merged earlier.

## Hardening notes (v0.1)

For self-hosters:

- Always set `AUTH_SECRET` to a 32+ byte secret. Rotate regularly.
- Postgres `POSTGRES_PASSWORD` defaults to `adelia_dev` — change for any non-localhost deployment.
- MinIO `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` default to `minioadmin` — same.
- Run all services behind TLS termination (nginx, Caddy, or Cloudflare Tunnel).
- AdelIA does not currently meet HIPAA, ISO 27001, or SOC 2. v0.1 is a personal documentation tool, not a medical device or covered entity processor.
