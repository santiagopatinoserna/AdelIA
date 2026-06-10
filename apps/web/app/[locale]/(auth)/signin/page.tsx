import { signIn } from "@/lib/auth";
import { useTranslations } from "next-intl";

export default function SignInPage() {
  const t = useTranslations();
  async function handleSignIn(formData: FormData) {
    "use server";
    await signIn("resend", {
      email: formData.get("email"),
      redirectTo: "/es/dashboard",
    });
  }
  return (
    <main className="mx-auto max-w-md px-6 py-24">
      <h1 className="text-2xl font-semibold">{t("common.appName")}</h1>
      <p className="mt-2 text-sm text-slate-600">{t("common.tagline")}</p>
      <form action={handleSignIn} className="mt-8 space-y-4">
        <input
          name="email"
          type="email"
          required
          placeholder={t("signin.emailPlaceholder")}
          className="w-full rounded-md border border-slate-300 px-3 py-2"
        />
        <button
          type="submit"
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-white hover:bg-slate-800"
        >
          {t("signin.sendMagicLink")}
        </button>
      </form>
    </main>
  );
}
