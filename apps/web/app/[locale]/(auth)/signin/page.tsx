"use client";

import { useActionState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Mail, ShieldCheck, Loader2, MailCheck, AlertCircle } from "lucide-react";

import { clearShowcaseHidden } from "@/lib/showcase-storage";
import { sendMagicLink, type SignInState } from "./actions";

const initial: SignInState = { status: "idle" };

export default function SignInPage() {
  const t = useTranslations("signin");
  const tc = useTranslations("common");
  const locale = useLocale();
  const [state, action, pending] = useActionState(sendMagicLink, initial);

  // Every login passes through here (magic link request, expired session):
  // forget "hide for now" so the capability showcase greets the next login.
  useEffect(() => {
    clearShowcaseHidden();
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-md">
        <div className="ad-card p-8 md:p-10">
          <span className="font-display text-2xl font-semibold tracking-tight text-ink">
            Adel<span className="text-accent-text">IA</span>
          </span>

          {/* The entrance fade lives on the form, not on the card: the wordmark
              paints at full opacity on the first frame, so Chrome records a First
              Contentful Paint. A root that starts at opacity 0 (ad-rise) never did:
              Lighthouse aborted with NO_FCP and the page had no FCP/LCP field data. */}
          <div className="ad-rise">
            {state.status === "sent" ? (
              <div className="mt-6">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                  <MailCheck className="h-6 w-6" strokeWidth={1.8} />
                </span>
                <h1 className="mt-4 text-2xl text-ink">{t("sentTitle")}</h1>
                <p className="mt-2 text-sm leading-relaxed text-ink-soft">
                  {t("sentBody", { email: state.email ?? "" })}
                </p>
                <form action={action} className="mt-6">
                  <input type="hidden" name="email" value={state.email ?? ""} />
                  <input type="hidden" name="locale" value={locale} />
                  <button
                    type="submit"
                    disabled={pending}
                    className="ad-btn ad-btn-ghost px-4 py-2 text-sm disabled:opacity-60"
                  >
                    {pending ? (
                      <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
                    ) : null}
                    {pending ? t("sending") : t("resend")}
                  </button>
                </form>
              </div>
            ) : (
              <>
                <h1 className="mt-6 text-2xl text-ink">{t("heading")}</h1>
                <p className="mt-2 text-sm leading-relaxed text-ink-soft">{t("instr")}</p>

                <p className="mt-4 flex items-center gap-1.5 text-xs text-primary-text">
                  <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-primary-text" strokeWidth={2} />
                  {t("secure")}
                </p>

                <form action={action} className="mt-5 space-y-3">
                  <input type="hidden" name="locale" value={locale} />
                  <label htmlFor="email" className="block text-sm font-medium text-ink-soft">
                    {t("emailLabel")}
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
                      placeholder={t("emailPlaceholder")}
                      className="w-full rounded-xl border border-line-control bg-surface py-2.5 pl-9 pr-3 text-base text-ink placeholder:text-ink-faint focus:border-primary-text"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={pending}
                    className="ad-btn ad-btn-primary w-full py-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {pending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
                        {t("sending")}
                      </>
                    ) : (
                      t("sendMagicLink")
                    )}
                  </button>
                </form>

                {state.status === "error" && (
                  <p
                    role="alert"
                    className="mt-4 flex items-start gap-1.5 rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text"
                  >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2.2} />
                    {t("errorMsg")}
                  </p>
                )}

                <p className="mt-5 text-xs text-ink-faint">{tc("tagline")}</p>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
