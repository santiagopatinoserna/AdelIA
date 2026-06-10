"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { sharing, type ShareLink } from "@/lib/sharing-client";

interface Props {
  briefingId: string;
  onClose: () => void;
}

const TTL_PRESETS = [
  { hours: 1, labelKey: "1h" },
  { hours: 24, labelKey: "24h" },
  { hours: 168, labelKey: "7d" },
  { hours: 720, labelKey: "30d" },
];

export function ShareDialog({ briefingId, onClose }: Props) {
  const t = useTranslations("briefing");
  const [ttl, setTtl] = useState(24);
  const [link, setLink] = useState<ShareLink | null>(null);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    setCreating(true);
    setError(null);
    try {
      const created = await sharing.create(briefingId, ttl);
      setLink(created);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  async function copyLink() {
    if (!link) return;
    await navigator.clipboard.writeText(link.share_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleRevoke() {
    if (!link) return;
    if (!confirm(t("share.revokeConfirm"))) return;
    try {
      await sharing.revoke(link.token);
      setLink(null);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">🔗 {t("share.title")}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-2xl text-slate-400 hover:text-slate-700"
          >
            ×
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
            {error}
          </div>
        )}

        {!link ? (
          <>
            <div className="mb-4">
              <label className="text-sm font-medium">{t("share.ttlLabel")}</label>
              <select
                value={ttl}
                onChange={(e) => setTtl(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              >
                {TTL_PRESETS.map((p) => (
                  <option key={p.hours} value={p.hours}>
                    {t(`share.ttl.${p.labelKey}`)}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating}
              className="w-full rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-400"
            >
              {creating ? t("share.creating") : t("share.createButton")}
            </button>
          </>
        ) : (
          <>
            <div className="mb-4 rounded border border-green-300 bg-green-50 p-3">
              <div className="text-xs uppercase text-green-700">
                {t("share.activeUntil", {
                  date: new Date(link.expires_at).toLocaleString(),
                })}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 break-all rounded border border-slate-300 bg-white px-2 py-1 text-xs">
                  {link.share_url}
                </code>
                <button
                  type="button"
                  onClick={copyLink}
                  className="rounded bg-slate-900 px-2 py-1 text-xs text-white"
                >
                  {copied ? "✅" : "📋"}
                </button>
              </div>
            </div>

            <div className="flex gap-2">
              <a
                href={sharing.publicPdfUrl(link.token)}
                target="_blank"
                rel="noopener"
                className="flex-1 rounded border border-slate-300 px-3 py-2 text-center text-sm hover:bg-slate-50"
              >
                📄 {t("downloadPdf")}
              </a>
              <button
                type="button"
                onClick={handleRevoke}
                className="flex-1 rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50"
              >
                🚫 {t("share.revoke")}
              </button>
            </div>
          </>
        )}

        <p className="mt-4 text-[10px] text-slate-500">{t("share.disclaimer")}</p>
      </div>
    </div>
  );
}
