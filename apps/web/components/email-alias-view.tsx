"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

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
      <h1 className="text-2xl font-semibold">📧 {t("title")}</h1>
      <p className="mt-1 text-sm text-slate-600">{t("subtitle")}</p>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">
              {t("aliasLabel")}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 break-all rounded border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-sm">
                {data.alias}
              </code>
              <button
                type="button"
                onClick={copyAlias}
                className="rounded bg-slate-900 px-3 py-2 text-sm text-white"
              >
                {copied ? "✅" : `📋 ${t("copy")}`}
              </button>
            </div>
          </div>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="font-medium">{t("gmailTitle")}</h3>
            <ol className="mt-2 space-y-1 text-sm text-slate-700">
              <li>{t("gmailStep1")}</li>
              <li>{t("gmailStep2")}</li>
              <li>{t("forwardStep", { alias: data.alias })}</li>
              <li>{t("gmailStep4")}</li>
            </ol>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="font-medium">{t("outlookTitle")}</h3>
            <ol className="mt-2 space-y-1 text-sm text-slate-700">
              <li>{t("outlookStep1")}</li>
              <li>{t("outlookStep2")}</li>
              <li>{t("forwardStep", { alias: data.alias })}</li>
            </ol>
          </section>

          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            ⚠️ {t("warning")}
          </div>
        </div>
      )}
    </main>
  );
}
