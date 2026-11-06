"use server";

import { claimGuest } from "@/lib/api-client";
import { signIn } from "@/lib/auth";

export type SaveState = { status: "idle" | "sent" | "error"; email?: string };

// "Guardar mi cuenta" (2026-11-06). The API mints a claim token for this
// guest and this email; the usual magic link carries it back to this page,
// where the account the link signs in adopts the guest (page.tsx). The link
// may be opened in another browser, so nothing here relies on this tab.
export async function sendSaveLink(_prev: SaveState, formData: FormData): Promise<SaveState> {
  const email = String(formData.get("email") ?? "").trim();
  const locale = String(formData.get("locale") ?? "es").trim() || "es";
  if (!email) return { status: "error" };
  let token: string;
  try {
    token = await claimGuest(email);
  } catch {
    return { status: "error", email };
  }
  try {
    const landing = await signIn("resend", {
      email,
      redirectTo: `/${locale}/dashboard/guardar?token=${encodeURIComponent(token)}`,
      redirect: false,
    });
    // Same check as the sign-in screen: a failed send comes back as the
    // URL of the error page, never as an exception.
    if (typeof landing === "string" && new URL(landing, "http://x").searchParams.has("error")) {
      return { status: "error", email };
    }
    return { status: "sent", email };
  } catch (err) {
    if (
      typeof err === "object" && err !== null && "digest" in err &&
      String((err as { digest?: unknown }).digest).startsWith("NEXT_REDIRECT")
    ) {
      throw err;
    }
    return { status: "error", email };
  }
}
