import { Pool } from "pg";
import type { Adapter, AdapterUser, VerificationToken } from "next-auth/adapters";

// Minimal Auth.js adapter for the magic-link (email) flow with JWT sessions.
// Backed by the SAME users table the FastAPI backend owns, so token.sub is a
// users.id the backend's foreign keys accept. Sessions stay JWT — no
// sessions/accounts tables needed; OAuth methods are stubs.

let pool: Pool | null = null;

function getPool(): Pool {
  if (!pool) {
    pool = new Pool({
      host: process.env.POSTGRES_HOST ?? "localhost",
      port: Number(process.env.POSTGRES_PORT ?? 5432),
      user: process.env.POSTGRES_USER ?? "adelia",
      password: process.env.POSTGRES_PASSWORD ?? "",
      database: process.env.POSTGRES_DB ?? "adelia",
      max: 3,
    });
  }
  return pool;
}

type UserRow = { id: string; email: string; email_verified: Date | null };

function toAdapterUser(row: UserRow): AdapterUser {
  return { id: row.id, email: row.email, emailVerified: row.email_verified };
}

export function AdeliaPgAdapter(): Adapter {
  return {
    async createUser(user) {
      const { rows } = await getPool().query<UserRow>(
        `INSERT INTO users (email, email_verified) VALUES ($1, $2)
         ON CONFLICT (email) DO UPDATE SET email_verified = EXCLUDED.email_verified
         RETURNING id, email, email_verified`,
        [user.email, user.emailVerified],
      );
      return toAdapterUser(rows[0]);
    },

    async getUser(id) {
      const { rows } = await getPool().query<UserRow>(
        "SELECT id, email, email_verified FROM users WHERE id = $1",
        [id],
      );
      return rows[0] ? toAdapterUser(rows[0]) : null;
    },

    async getUserByEmail(email) {
      const { rows } = await getPool().query<UserRow>(
        "SELECT id, email, email_verified FROM users WHERE email = $1",
        [email],
      );
      return rows[0] ? toAdapterUser(rows[0]) : null;
    },

    async updateUser(user) {
      const { rows } = await getPool().query<UserRow>(
        `UPDATE users SET email_verified = COALESCE($2, email_verified)
         WHERE id = $1 RETURNING id, email, email_verified`,
        [user.id, user.emailVerified ?? null],
      );
      return toAdapterUser(rows[0]);
    },

    async createVerificationToken(token: VerificationToken) {
      await getPool().query(
        "INSERT INTO verification_tokens (identifier, token, expires) VALUES ($1, $2, $3)",
        [token.identifier, token.token, token.expires],
      );
      return token;
    },

    async useVerificationToken({ identifier, token }) {
      const { rows } = await getPool().query<VerificationToken>(
        `DELETE FROM verification_tokens WHERE identifier = $1 AND token = $2
         RETURNING identifier, token, expires`,
        [identifier, token],
      );
      return rows[0] ?? null;
    },

    // JWT sessions + email-only provider: OAuth account methods never persist.
    async getUserByAccount() {
      return null;
    },
    async linkAccount() {
      return undefined;
    },
  };
}
