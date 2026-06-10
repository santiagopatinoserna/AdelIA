import NextAuth, { type NextAuthConfig } from "next-auth";
import Resend from "next-auth/providers/resend";
import { SignJWT, decodeJwt } from "jose";

import { AdeliaPgAdapter } from "./auth-adapter";

declare module "next-auth" {
  interface Session {
    jwt?: string;
  }
}

// JWT is Record<string,unknown> in next-auth v5 — use a helper type for our custom fields
type AdeliaToken = { rawJwt?: string };

export const authConfig: NextAuthConfig = {
  adapter: AdeliaPgAdapter(),
  providers: [
    Resend({
      from: "AdelIA <noreply@adelia.godi.ai>",
      apiKey: process.env.RESEND_API_KEY,
    }),
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
