import NextAuth, { type NextAuthConfig } from "next-auth";
import Resend from "next-auth/providers/resend";
import Credentials from "next-auth/providers/credentials";
import { SignJWT, decodeJwt } from "jose";

import { AdeliaPgAdapter } from "./auth-adapter";

declare module "next-auth" {
  interface Session {
    jwt?: string;
  }
}

// JWT is Record<string,unknown> in next-auth v5 — use a helper type for our custom fields
type AdeliaToken = { rawJwt?: string };

const API_URL =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// "La demo es la app real" (2026-11-06). A visitor's first question on the
// landing signs her in as a guest: the API creates the row and Lucía
// (POST /guest, adelia/services/guest.py) and this provider puts that id in
// the SAME session JWT an account gets, so every dashboard route, the proxy
// and the API's own checks treat her like anyone else. Nothing she sends is
// read: the only input is the language, and the address is forwarded so the
// API's per-address brake on guest creation sees her, not this server.
const guestProvider = Credentials({
  id: "guest",
  name: "guest",
  credentials: { locale: {} },
  async authorize(credentials, request) {
    const locale = typeof credentials?.locale === "string" ? credentials.locale.slice(0, 8) : "es";
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const forwarded = request?.headers?.get?.("x-forwarded-for");
    if (forwarded) headers["X-Forwarded-For"] = forwarded;
    try {
      const res = await fetch(`${API_URL}/guest`, {
        method: "POST", headers, body: JSON.stringify({ locale }), cache: "no-store",
      });
      if (!res.ok) return null;
      const { user_id } = (await res.json()) as { user_id?: string };
      return user_id ? { id: user_id } : null;
    } catch {
      return null;
    }
  },
});

export const authConfig: NextAuthConfig = {
  adapter: AdeliaPgAdapter(),
  providers: [
    Resend({
      from: "AdelIA <noreply@adelia.godi.ai>",
      apiKey: process.env.RESEND_API_KEY,
    }),
    guestProvider,
  ],
  // Bare path — the next-intl middleware prefixes the active locale.
  pages: { signIn: "/signin" },
  session: { strategy: "jwt" },
  secret: process.env.AUTH_SECRET,
  // Self-hosted deploys (Fly.io, localhost prod) sit behind a proxy or a
  // non-canonical host; Auth.js v5 rejects them with UntrustedHost otherwise.
  trustHost: true,
  callbacks: {
    async jwt({ token, user }) {
      if (user?.id) token.sub = user.id;
      // Sign an HS256 JWT for the FastAPI backend bridge.
      // Backend (T6 auth.py) verifies with the same AUTH_SECRET.
      const t = token as typeof token & AdeliaToken;
      // Re-sign when missing OR within 24h of expiry: the Auth.js session
      // lives 30 days, the bridge JWT 7 — without renewal every API call
      // turns 401 on day 8 while the user still looks signed in.
      let needsSigning = !t.rawJwt;
      if (t.rawJwt) {
        try {
          const { exp } = decodeJwt(t.rawJwt);
          needsSigning = !exp || exp * 1000 - Date.now() < 24 * 60 * 60 * 1000;
        } catch {
          needsSigning = true;
        }
      }
      if (t.sub && needsSigning) {
        const secret = new TextEncoder().encode(process.env.AUTH_SECRET ?? "");
        t.rawJwt = await new SignJWT({
          sub: t.sub,
          email: t.email ?? undefined,
        })
          .setProtectedHeader({ alg: "HS256" })
          .setIssuedAt()
          .setExpirationTime("7d")
          .sign(secret);
      }
      return t;
    },
    async session({ session, token }) {
      const t = token as typeof token & AdeliaToken;
      if (t.sub && session.user) {
        (session.user as typeof session.user & { id?: string }).id = t.sub;
      }
      session.jwt = t.rawJwt;
      return session;
    },
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
