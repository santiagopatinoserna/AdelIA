"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Send, Copy, Check } from "lucide-react";

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
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Send className="h-5 w-5 text-pine-500" strokeWidth={2} />
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
          <ol className="space-y-3 text-sm text-ink">
            <li>
              <span className="font-mono font-semibold text-pine-600">1.</span>{" "}
              <a
                href={data.bot_url}
                target="_blank"
                rel="noopener"
                className="font-medium text-pine-600 underline decoration-pine-200 underline-offset-2 hover:text-pine-700"
              >
                {t("openBot", { url: data.bot_url })}
              </a>
            </li>
            <li>
              <span className="font-mono font-semibold text-pine-600">2.</span> {t("step2")}
              <div className="mt-2 flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-xs">
                <code className="flex-1 break-all text-ink">/start {data.link_token}</code>
                <button
                  type="button"
                  onClick={copyCommand}
                  className="ad-btn ad-btn-primary px-2 py-1 text-xs"
                  aria-label={t("copy")}
                >
                  {copied ? <Check className="h-3.5 w-3.5" strokeWidth={2.4} /> : <Copy className="h-3.5 w-3.5" strokeWidth={2.2} />}
                </button>
              </div>
              <p className="mt-1 text-xs text-ink-faint">{t("tokenExpiry")}</p>
            </li>
            <li>
              <span className="font-mono font-semibold text-pine-600">3.</span> {t("step3")}
            </li>
          </ol>
        </div>
      )}
    </main>
  );
}
