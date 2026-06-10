"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import type { TelegramLinkDTO } from "@/lib/api-client-browser";

export function TelegramLinkView({
  data,
  error,
}: {
  data: TelegramLinkDTO | null;
  error: string | null;
}) {
  const t = useTranslations("ingestion.telegram");
  const [copied, setCopied] = useState(false);

  async function copyCommand() {
    if (!data) return;
    await navigator.clipboard.writeText(`/start ${data.link_token}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold">💬 {t("title")}</h1>
      <p className="mt-1 text-sm text-slate-600">{t("subtitle")}</p>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-4">
          <ol className="space-y-3 text-sm">
            <li>
              <span className="font-medium">1.</span>{" "}
              <a
                href={data.bot_url}
                target="_blank"
                rel="noopener"
                className="text-blue-700 underline"
              >
                {t("openBot", { url: data.bot_url })}
              </a>
            </li>
            <li>
              <span className="font-medium">2.</span> {t("step2")}
              <div className="mt-2 flex items-center gap-2 rounded border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs">
                <code className="break-all">/start {data.link_token}</code>
                <button
                  type="button"
                  onClick={copyCommand}
                  className="rounded bg-slate-900 px-2 py-1 text-white"
                >
                  {copied ? "✅" : t("copy")}
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-500">{t("tokenExpiry")}</p>
            </li>
            <li>
              <span className="font-medium">3.</span> {t("step3")}
            </li>
          </ol>
        </div>
      )}
    </main>
  );
}
