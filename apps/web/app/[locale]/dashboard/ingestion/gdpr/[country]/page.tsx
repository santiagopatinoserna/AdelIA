"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check, Copy, FileText } from "lucide-react";

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
      .catch((e) => setError(t("actionError")));
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
      <h1 className="flex items-center gap-2 text-2xl text-ink">
        <FileText className="h-5 w-5 text-primary-text" strokeWidth={2} />
        {tpl.country} · {tpl.authority}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">
        {t("meta", {
          legalBasis: tpl.legal_basis,
          deadline: tpl.response_deadline,
          language: tpl.output_language,
        })}
      </p>
      <button
        type="button"
        onClick={copyTemplate}
        className="ad-btn ad-btn-primary mt-4 px-4 py-2 text-sm"
      >
        {copied ? (
          <>
            <Check className="h-4 w-4" />
            {t("copied")}
          </>
        ) : (
          <>
            <Copy className="h-4 w-4" />
            {t("copyTemplate")}
          </>
        )}
      </button>
      <pre className="mt-6 whitespace-pre-wrap rounded-lg border border-line bg-surface-2 p-6 font-mono text-xs text-ink">
        {tpl.markdown}
      </pre>
    </main>
  );
}
