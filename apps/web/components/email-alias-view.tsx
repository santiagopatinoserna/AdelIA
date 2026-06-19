"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Mail, Copy, Check, AlertTriangle } from "lucide-react";

import type { EmailAliasDTO } from "@/lib/api-client-browser";

export function EmailAliasView({
  data,
  error,
}: {
  data: EmailAliasDTO | null;
  error: string | null;
}) {
  const t = useTranslations("ingestion.email");
  const [copied, setCopied] = useState(false);

  async function copyAlias() {
    if (!data) return;
    await navigator.clipboard.writeText(data.alias);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Mail className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("title")}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">{t("subtitleFriendly")}</p>

      {error && (
        <div className="mt-4 rounded-lg border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {error}
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-4">
          <div className="ad-card p-4">
            <div className="ad-eyebrow">{t("aliasLabelFriendly")}</div>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 break-all rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-sm text-ink">
                {data.alias}
              </code>
              <button
                type="button"
                onClick={copyAlias}
                className="ad-btn ad-btn-primary px-3 py-2 text-sm"
              >
                {copied ? <Check className="h-4 w-4" strokeWidth={2.4} /> : <Copy className="h-4 w-4" strokeWidth={2.2} />}
                <span className="hidden sm:inline">{t("copy")}</span>
              </button>
            </div>
          </div>

          <section className="ad-card p-4">
            <h3 className="font-medium text-ink">{t("gmailTitle")}</h3>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-soft marker:text-pine-400">
              <li>{t("gmailStep1")}</li>
              <li>{t("gmailStep2")}</li>
              <li>{t("forwardStep", { alias: data.alias })}</li>
              <li>{t("gmailStep4")}</li>
            </ol>
          </section>

          <section className="ad-card p-4">
            <h3 className="font-medium text-ink">{t("outlookTitle")}</h3>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-soft marker:text-pine-400">
              <li>{t("outlookStep1")}</li>
              <li>{t("outlookStep2")}</li>
              <li>{t("forwardStep", { alias: data.alias })}</li>
            </ol>
          </section>

          <div className="flex items-start gap-2 rounded-lg border border-honey-200 bg-honey-100/60 p-3 text-xs text-ink">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-honey-700" strokeWidth={2.2} />
            {t("warningFriendly")}
          </div>
        </div>
      )}
    </main>
  );
}
