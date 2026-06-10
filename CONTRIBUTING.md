# Contributing to AdelIA

Thanks for considering a contribution. AdelIA is an open source project under AGPL-3.0.

## Sign-off (DCO)

All commits must be signed off:

```bash
git commit -s -m "feat: your change"
```

This appends `Signed-off-by: Your Name <you@example.com>` to the commit message, certifying that you have the right to contribute the change under the AGPL-3.0 license. See the [Developer Certificate of Origin](https://developercertificate.org/).

## Workflow

1. Fork the repo and create a feature branch from `main`.
2. Run tests locally: `pnpm test:api` and `pnpm --filter @adelia/web typecheck`.
3. Open a PR against `main`. Reference any related Issue.
4. Squash on merge. Commit messages follow Conventional Commits:
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation only
   - `chore:` tooling, deps, or non-functional changes
   - `refactor:` internal change without behavior modification
   - `test:` test additions/changes only

## Code style

- **Python (apps/api):** ruff (line-length 100, target Python 3.12). Run `uv --directory apps/api run ruff check`.
- **TypeScript (apps/web):** strict mode + bundler resolution. Run `pnpm --filter @adelia/web typecheck`.

Tests must accompany substantive changes. Backend uses pytest; frontend tests are not required in v0.1 (Playwright integration is on the v0.1.1 roadmap).

## Known v0.1.1 carry-overs

These are tracked tech debt items that contributions are welcome on:

- **Locale-aware Auth.js redirects:** `pages.signIn` and signin `redirectTo` in `lib/auth.ts` and `app/[locale]/(auth)/signin/page.tsx` are hardcoded to `/es/...` because Auth.js v5 takes a static string. Solving this requires custom middleware that resolves the active locale at runtime.
- **`Link` migration:** `apps/web/app/[locale]/dashboard/page.tsx` and `apps/web/components/document-card.tsx` still import from `next/link` and use manual `${locale}` template literals. Migrate to `@/lib/navigation` Link.
- **Hydration-safe date formatting:** `new Date(...).toLocaleString()` is called without a locale argument in `document-card.tsx` and `dashboard/documents/[id]/page.tsx`. Use `next-intl`'s `useFormatter` or pass an explicit locale.
- **Pagination on `GET /documents`:** the list endpoint returns all of a user's documents with no `?limit=&offset=` parameters.
- **Auto-poll on document detail page:** today the user manually reloads to see status flip from `processing` → `ready`. v0.1.1 should add a client-side poller until status changes.
- **`auth_secret` empty default in API config:** `apps/api/adelia/config.py` defaults to `""` which silently accepts forged tokens with empty signatures if the env var is missing. Should fail-fast.
- **Server-only guard on `api-client.ts`:** add `import "server-only"` to prevent accidental client imports.

## Reporting issues

Use GitHub Issues. Include reproduction steps, expected vs actual, and AdelIA version (commit SHA or tag) when applicable.

## License

AdelIA is AGPL-3.0. By contributing, you agree your contribution is licensed under AGPL-3.0 alongside the project.
