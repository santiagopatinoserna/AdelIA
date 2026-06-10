"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { ingestion } from "@/lib/api-client-browser";
import type { GDPRTemplateContent } from "@/lib/enrichment-types";

export default function GdprTemplateViewerPage() {
  const t = useTranslations("ingestion.gdpr");
  const tCommon = useTranslations("common");
  const params = useParams<{ country: string }>();
  const country = params?.country ?? "";
  const [tpl, setTpl] = useState<GDPRTemplateContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!country) return;
    ingestion
      .getGdprTemplate(country)
      .then(setTpl)
      .catch((e) => setError(String(e)));
  }, [country]);

  async function copyTemplate() {
    if (!tpl) return;
    await navigator.clipboard.writeText(tpl.markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (error) return <main className="mx-auto max-w-3xl px-6 py-10">{error}</main>;
  if (!tpl) return <main className="mx-auto max-w-3xl px-6 py-10">{tCommon("loading")}</main>;

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{tpl.country} — {tpl.authority}</h1>
      <p className="mt-1 text-sm text-slate-600">
        {t("meta", {
          legalBasis: tpl.legal_basis,
          deadline: tpl.response_deadline,
          language: tpl.output_language,
        })}
      </p>
      <button
        type="button"
        onClick={copyTemplate}
        className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
      >
        {copied ? `✅ ${t("copied")}` : `📋 ${t("copyTemplate")}`}
      </button>
      <pre className="mt-6 whitespace-pre-wrap rounded border border-slate-200 bg-white p-6 font-mono text-xs">
        {tpl.markdown}
      </pre>
    </main>
  );
}
