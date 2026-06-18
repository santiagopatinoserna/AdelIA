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
    await signIn("resend", {
      email,
      redirectTo: `/${locale}/dashboard`,
      redirect: false,
    });
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
