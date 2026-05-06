# AdelIA

Open source personal medical vault + AI analysis (self-analysis + doctor briefing).

**Status:** v0.1 in development. See `docs/specs/` and `docs/plans/`.

**License:** AGPL-3.0. See `LICENSE`.

## Quickstart (dev)

```bash
pnpm install
pnpm dev:infra    # Docker: Postgres + MinIO
pnpm dev:api      # FastAPI on :8000
pnpm dev:web      # Next.js on :3000
```

Visit http://localhost:3000/es
