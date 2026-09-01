import { Pool } from "pg";
import { SignJWT } from "jose";
import { encode } from "next-auth/jwt";

// Mint a REAL Auth.js session cookie: same encode + AUTH_SECRET the app
// uses, so nothing test-specific ships in production code. The user row is
// seeded directly in Postgres (FK target for everything user-scoped).

const COOKIE_NAME = "authjs.session-token";

function env(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (v === undefined) throw new Error(`${name} not set for e2e`);
  return v;
}

export async function seedUserAndSessionCookie(email: string) {
  const pool = new Pool({
    host: env("POSTGRES_HOST", "localhost"),
    port: Number(env("POSTGRES_PORT", "5434")),
    user: env("POSTGRES_USER", "adelia"),
    password: env("POSTGRES_PASSWORD", "adelia_dev"),
    database: env("POSTGRES_DB", "adelia"),
  });
  // Seed with an active trial: dashboard routes redirect to /billing unless
  // subscription_status is in {"trialing", "active"} (see
  // apps/api/adelia/routers/billing.py ACTIVE_STATUSES). Without this, every
  // dashboard-gated e2e test hits the Stripe paywall screen instead of the
  // page under test.
  // onboarded_at is stamped on purpose: a seeded e2e user stands for an
  // EXISTING account, and dashboard/layout.tsx sends an account that has
  // never been asked about the baby to /{locale}/onboarding before the panel
  // (audit 4.3). Without this every dashboard spec would land on the
  // onboarding screen instead of the page under test. The onboarding e2e
  // seeds its own user with onboarded_at NULL.
  const { rows } = await pool.query(
    `INSERT INTO users (email, subscription_status, trial_end, onboarded_at)
     VALUES ($1, 'trialing', now() + interval '30 days', now())
     ON CONFLICT (email) DO UPDATE
       SET email = EXCLUDED.email,
           subscription_status = EXCLUDED.subscription_status,
           trial_end = EXCLUDED.trial_end,
           onboarded_at = EXCLUDED.onboarded_at
     RETURNING id`,
    [email],
  );
  await pool.end();
  const userId: string = rows[0].id;

  const secret = env("AUTH_SECRET");
  const rawJwt = await new SignJWT({ sub: userId, email })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(new TextEncoder().encode(secret));

  const sessionToken = await encode({
    token: { sub: userId, email, rawJwt },
    secret,
    salt: COOKIE_NAME,
  });

  return {
    userId,
    cookie: {
      name: COOKIE_NAME,
      value: sessionToken,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax" as const,
      secure: false,
    },
  };
}
