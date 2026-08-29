# AdelIA web — production image (Next.js standalone output).
# Build context must be the REPO ROOT (pnpm workspace):
#   docker build -f apps/web/Dockerfile .
FROM node:20-bookworm-slim AS builder

RUN corepack enable && corepack prepare pnpm@10.11.0 --activate

WORKDIR /repo
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @adelia/web...

COPY apps/web apps/web
# NEXT_PUBLIC_ vars are inlined at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Optional build id override (next.config.ts); empty = UTC timestamp default.
ARG ADELIA_BUILD_ID=
ENV ADELIA_BUILD_ID=$ADELIA_BUILD_ID
RUN pnpm --filter @adelia/web build

FROM node:20-bookworm-slim AS runner
ENV NODE_ENV=production
WORKDIR /app

# Standalone bundle carries its own pruned node_modules.
COPY --from=builder /repo/apps/web/.next/standalone ./
COPY --from=builder /repo/apps/web/.next/static ./apps/web/.next/static
# Static assets are NOT part of the standalone output: without this line the
# service worker, icons and offline page 404 (or fall through to the HTML
# catch-all) in production, so the PWA is neither installable nor offline.
COPY --from=builder /repo/apps/web/public ./apps/web/public

EXPOSE 3000
CMD ["node", "apps/web/server.js"]
