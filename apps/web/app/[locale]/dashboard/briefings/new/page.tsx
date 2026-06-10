"use client";

import { useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { briefings as briefingsApi } from "@/lib/api-client-browser";
import type { Specialty } from "@/lib/briefing-types";
import { SpecialtySelect } from "@/components/briefing/specialty-select";

export default function NewBriefingPage() {
  const t = useTranslations();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params?.locale ?? "es";
  const [specialty, setSpecialty] = useState<Specialty>("default");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const created = await briefingsApi.create({ target_specialty: specialty });
      router.push(`/${locale}/dashboard/briefings/${created.id}`);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="mb-6 text-2xl font-semibold">{t("briefing.newButton")}</h1>
      <div className="space-y-6">
        <SpecialtySelect value={specialty} onChange={setSpecialty} disabled={submitting} />
        {error && (
          <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
        >
          {submitting ? t("briefing.status.processing") : t("briefing.createButton")}
        </button>
      </div>
    </main>
  );
}
