"use client";

import { useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { briefings as briefingsApi } from "@/lib/api-client-browser";
import { useActiveProfile } from "@/lib/profile-context";
import type { Specialty } from "@/lib/briefing-types";
import { SpecialtySelect } from "@/components/briefing/specialty-select";

export default function NewBriefingPage() {
  const t = useTranslations();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params?.locale ?? "es";
  // The briefing is the artefact a parent prints and hands to a specialist,
  // so it has to be about ONE child. Without this it was assembled from the
  // whole account (audit 4.1).
  const { activeId: activeProfileId } = useActiveProfile();
  const [specialty, setSpecialty] = useState<Specialty | "">("pediatrics");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = specialty !== "";

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await briefingsApi.create({
        target_specialty: specialty as Specialty,
        locale: locale as "es" | "en" | "fr",
        profile_id: activeProfileId,
      });
      router.push(`/${locale}/dashboard/briefings/${created.id}`);
    } catch (e) {
      setError(t("common.actionError"));
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="mb-6 text-2xl text-ink">{t("briefing.newButton")}</h1>
      <div className="space-y-6">
        <SpecialtySelect value={specialty} onChange={setSpecialty} disabled={submitting} />
        {error && (
          <div className="rounded-lg border border-error-tint-line bg-error-tint p-3 text-sm text-error-text">
            {error}
          </div>
        )}
        {submitting && (
          <div className="ad-card space-y-3 p-4" aria-live="polite">
            <div className="flex items-center gap-3">
              <span
                className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-primary-tint-line border-t-pine-600"
                role="status"
                aria-label={t("briefing.generatingTitle")}
              />
              <div>
                <p className="text-sm font-medium text-ink">{t("briefing.generatingTitle")}</p>
                <p className="text-sm text-ink-soft">{t("briefing.generatingPatience")}</p>
              </div>
            </div>
            <div className="ad-rise space-y-2.5">
              <div className="h-3 w-11/12 rounded bg-surface-2" />
              <div className="h-3 w-9/12 rounded bg-surface-2" />
              <div className="h-3 w-10/12 rounded bg-surface-2" />
            </div>
          </div>
        )}
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !canSubmit}
            className="ad-btn ad-btn-primary px-4 py-2 text-sm disabled:opacity-50"
          >
            {submitting ? t("briefing.status.processing") : t("briefing.createButton")}
          </button>
          {!canSubmit && !submitting && (
            <p className="text-sm text-ink-soft">{t("briefing.specialty.required")}</p>
          )}
        </div>
      </div>
    </main>
  );
}
