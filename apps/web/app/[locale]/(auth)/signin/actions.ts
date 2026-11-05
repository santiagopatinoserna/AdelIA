"use server";

import { signIn } from "@/lib/auth";

export type SignInState = { status: "idle" | "sent" | "error"; email?: string };

// Sends the magic link without an HTTP redirect (redirect: false) so the client
// can show a "check your inbox" confirmation instead of bouncing the mom to a
// blank verify page. The email is still dispatched by the Resend provider.
export async function sendMagicLink(
  _prev: SignInState,
  formData: FormData,
): Promise<SignInState> {
  const email = String(formData.get("email") ?? "").trim();
  const locale = String(formData.get("locale") ?? "es").trim() || "es";
  if (!email) return { status: "error" };
  try {
    const landing = await signIn("resend", {
      email,
      redirectTo: `/${locale}/dashboard`,
      redirect: false,
    });
    // signIn only throws AuthErrors. A failed send (Resend rejecting the
    // key, the network down) comes back as the URL of the error page,
    // "/api/auth/error?error=Configuration", and was announced as "check your
    // inbox": she waited for an email that had never left (RECORRIDO_POC.md).
    if (linkWasNotSent(landing)) return { status: "error", email };
    return { status: "sent", email };
  } catch (err) {
    // Never swallow a Next redirect (it surfaces as a thrown error with a
    // NEXT_REDIRECT digest) — only genuine send failures become "error".
    if (
      typeof err === "object" &&
      err !== null &&
      "digest" in err &&
      typeof (err as { digest?: unknown }).digest === "string" &&
      (err as { digest: string }).digest.startsWith("NEXT_REDIRECT")
    ) {
      throw err;
    }
    return { status: "error", email };
  }
}

// The email provider's success lands on /api/auth/verify-request; any landing
// that carries an `error` parameter is a failure, whatever page it names.
function linkWasNotSent(landing: unknown): boolean {
  if (typeof landing !== "string") return false;
  try {
    return new URL(landing, "http://localhost").searchParams.has("error");
  } catch {
    return false;
  }
}
