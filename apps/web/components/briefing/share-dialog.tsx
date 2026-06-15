"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Share2, X, Copy, Check, FileDown, Ban } from "lucide-react";

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

  // Escape closes the dialog (standard modal behavior).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-pine-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="ad-card w-full max-w-lg p-6 shadow-glow"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg text-pine-900">
            <Share2 className="h-4 w-4 text-pine-500" strokeWidth={2} />
            {t("share.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ad-btn ad-btn-ghost h-8 w-8 p-0"
          >
            <X className="h-4 w-4" strokeWidth={2} />
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded-lg border border-clay-100 bg-clay-50 p-2 text-sm text-clay-700">
            {error}
          </div>
        )}

        {!link ? (
          <>
            <div className="mb-4">
              <label className="text-sm font-medium text-ink">{t("share.ttlLabel")}</label>
              <select
                value={ttl}
                onChange={(e) => setTtl(Number(e.target.value))}
                className="mt-1.5 w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
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
              className="ad-btn ad-btn-primary w-full py-2 text-sm disabled:opacity-50"
            >
              {creating ? t("share.creating") : t("share.createButton")}
            </button>
          </>
        ) : (
          <>
            <div className="mb-4 rounded-xl border border-pine-100 bg-pine-50 p-3">
              <div className="ad-eyebrow">
                {t("share.activeUntil", {
                  date: new Date(link.expires_at).toLocaleString(),
                })}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 break-all rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink">
                  {link.share_url}
                </code>
                <button
                  type="button"
                  onClick={copyLink}
                  aria-label={t("share.title")}
                  className="ad-btn ad-btn-primary px-2 py-1.5 text-xs"
                >
                  {copied ? <Check className="h-3.5 w-3.5" strokeWidth={2.4} /> : <Copy className="h-3.5 w-3.5" strokeWidth={2.2} />}
                </button>
              </div>
            </div>

            <div className="flex gap-2">
              <a
                href={sharing.publicPdfUrl(link.token)}
                target="_blank"
                rel="noopener"
                className="ad-btn ad-btn-ghost flex-1 px-3 py-2 text-sm"
              >
                <FileDown className="h-4 w-4" strokeWidth={2} />
                {t("downloadPdf")}
              </a>
              <button
                type="button"
                onClick={handleRevoke}
                className="ad-btn flex-1 border border-clay-100 px-3 py-2 text-sm text-clay-600 hover:bg-clay-50"
              >
                <Ban className="h-4 w-4" strokeWidth={2} />
                {t("share.revoke")}
              </button>
            </div>
          </>
        )}

        <p className="mt-4 text-[10px] text-ink-faint">{t("share.disclaimer")}</p>
      </div>
    </div>
  );
}
