import { signIn } from "@/lib/auth";
import { useTranslations } from "next-intl";
import { Mail, ShieldCheck } from "lucide-react";

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
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-md">
        <div className="ad-card ad-rise p-8 md:p-10">
          <span className="font-display text-2xl font-semibold tracking-tight text-pine-900">
            Adel<span className="text-honey-500">IA</span>
          </span>
          <h1 className="mt-6 text-2xl text-pine-900">{t("signin.sendMagicLink")}</h1>
          <p className="mt-2 text-sm text-ink-soft">{t("common.tagline")}</p>
          <form action={handleSignIn} className="mt-7 space-y-3">
            <label htmlFor="email" className="block text-sm font-medium text-ink-soft">
              {t("signin.emailLabel")}
            </label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" strokeWidth={2} />
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                inputMode="email"
                autoCapitalize="off"
                spellCheck={false}
                placeholder={t("signin.emailPlaceholder")}
                className="w-full rounded-xl border border-line-strong bg-surface py-2.5 pl-9 pr-3 text-base text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
              />
            </div>
            <button type="submit" className="ad-btn ad-btn-primary w-full py-2.5 text-sm">
              {t("signin.sendMagicLink")}
            </button>
          </form>
          <p className="mt-5 flex items-center gap-1.5 text-xs text-ink-faint">
            <ShieldCheck className="h-3.5 w-3.5 text-pine-400" strokeWidth={2} />
            {t("common.tagline")}
          </p>
        </div>
      </div>
    </main>
  );
}
