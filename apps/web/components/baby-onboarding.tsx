"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Baby, Loader2 } from "lucide-react";

import { onboarding } from "@/lib/api-client-browser";

// Three questions, asked once, before the panel (audit 4.3). Between the magic
// link and the first useful pixel there used to be a credit card and nothing
// about the child, so every age-gated clinical rule ran blind: the "under 3
// months with a fever" red flag could not fire, the lab ranges compared a
// newborn against adult values, and the briefing header printed "0 años".
//
// Skippable on purpose, and the skip is one tap: a parent arriving at 3 a.m.
// with a feverish baby has to reach the app first and answer forms later. The
// agent asks for the date of birth again, in context, when it needs it.
export function BabyOnboardingForm({ locale }: { locale: string }) {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const [name, setName] = useState("");
  const [dob, setDob] = useState("");
  const [sex, setSex] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `max` on the date input blocks the picker; this blocks a typed value.
  // A date of birth in the future makes the age unknown, which silently
  // switches off every age-gated rule instead of failing loudly.
  const today = new Date().toISOString().slice(0, 10);

  function leave() {
    router.replace(`/${locale}/dashboard`);
    // The dashboard layout reads the onboarding status server-side; without
    // a refresh the cached RSC payload would bounce her straight back here.
    router.refresh();
  }

  async function handleSave() {
    if (busy) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("errorName"));
      return;
    }
    if (dob && dob > today) {
      setError(t("errorFutureDob"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onboarding.complete({
        display_name: trimmed,
        date_of_birth: dob || null,
        sex: (sex || null) as "M" | "F" | "other" | null,
      });
      leave();
    } catch {
      setError(t("errorGeneric"));
      setBusy(false);
    }
  }

  async function handleSkip() {
    if (busy) return;
    setBusy(true);
    try {
      await onboarding.skip();
    } catch {
      // Never trap her here over a failed bookkeeping call: the screen is
      // optional, so a network hiccup must not become a locked door. She
      // will simply be asked once more next time.
    }
    leave();
  }

  return (
    <form
      className="ad-card space-y-5 p-6"
      onSubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
    >
      <div>
        <label htmlFor="baby-name" className="block text-sm font-medium text-ink">
          {t("nameLabel")}
        </label>
        <input
          id="baby-name"
          type="text"
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("namePlaceholder")}
          maxLength={128}
          className="ad-field mt-1.5 min-h-[44px] w-full px-3 py-2 text-sm"
        />
      </div>

      <div>
        <label htmlFor="baby-dob" className="block text-sm font-medium text-ink">
          {t("dobLabel")}
        </label>
        <input
          id="baby-dob"
          type="date"
          max={today}
          value={dob}
          onChange={(e) => setDob(e.target.value)}
          aria-describedby="baby-dob-hint"
          className="ad-field mt-1.5 min-h-[44px] w-full px-3 py-2 text-sm"
        />
        <p id="baby-dob-hint" className="mt-1.5 text-xs text-ink-faint">
          {t("dobHint")}
        </p>
      </div>

      <div>
        <label htmlFor="baby-sex" className="block text-sm font-medium text-ink">
          {t("sexLabel")}
        </label>
        <select
          id="baby-sex"
          value={sex}
          onChange={(e) => setSex(e.target.value)}
          className="ad-field mt-1.5 min-h-[44px] w-full px-3 py-2 text-sm"
        >
          <option value="">{t("sexUnset")}</option>
          <option value="M">{t("sexMale")}</option>
          <option value="F">{t("sexFemale")}</option>
          <option value="other">{t("sexOther")}</option>
        </select>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-xl border border-error-tint-line bg-error-tint p-3 text-sm text-error-text"
        >
          {error}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row-reverse sm:items-center">
        <button
          type="submit"
          disabled={busy}
          className="ad-btn ad-btn-primary min-h-[48px] w-full px-5 py-3 text-sm disabled:opacity-60 sm:w-auto"
        >
          {busy ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
              {t("saving")}
            </>
          ) : (
            <>
              <Baby className="h-4 w-4" strokeWidth={2} />
              {t("submit")}
            </>
          )}
        </button>
        <button
          type="button"
          onClick={handleSkip}
          disabled={busy}
          className="ad-btn ad-btn-ghost min-h-[48px] w-full px-5 py-3 text-sm disabled:opacity-60 sm:w-auto"
        >
          {t("skip")}
        </button>
      </div>

      <p className="text-xs text-ink-faint">{t("privacy")}</p>
    </form>
  );
}
