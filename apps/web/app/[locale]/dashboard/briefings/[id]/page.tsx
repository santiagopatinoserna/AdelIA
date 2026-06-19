"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { FileDown, Share2, RefreshCw, Upload } from "lucide-react";

import Link from "next/link";

import { briefings as briefingsApi } from "@/lib/api-client-browser";
import type { BriefingDetailOut } from "@/lib/briefing-types";
import { sharing } from "@/lib/sharing-client";
import { BriefingDetail } from "@/components/briefing/briefing-detail";
import { ShareDialog } from "@/components/briefing/share-dialog";
import { StaleBanner } from "@/components/briefing/stale-banner";

export default function BriefingDetailPage() {
  const t = useTranslations();
  const router = useRouter();
  const params = useParams<{ locale: string; id: string }>();
  const locale = params?.locale ?? "es";
  const id = params?.id ?? "";

  const [briefing, setBriefing] = useState<BriefingDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [timedOut, setTimedOut] = useState(false);

  const fetchBriefing = useCallback(async () => {
    if (!id) return;
    try {
      const b = await briefingsApi.getById(id);
      setBriefing(b);
    } catch (e) {
      setError(t("common.actionError"));
    }
  }, [id]);

  useEffect(() => {
    fetchBriefing();
  }, [fetchBriefing]);

  useEffect(() => {
    // Stop polling once the briefing is no longer processing, or once we've
    // hit the safety cap (~10 min) so the page never spins forever.
    if (!briefing || briefing.status !== "processing" || timedOut) return;
    const POLL_TIMEOUT_MS = 10 * 60 * 1000;
    const interval = setInterval(fetchBriefing, 2000);
    const timeout = setTimeout(() => setTimedOut(true), POLL_TIMEOUT_MS);
    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [briefing, fetchBriefing, timedOut]);

  async function handleRegenerate() {
    if (!id) return;
    setRegenerating(true);
    try {
      const newBriefing = await briefingsApi.regenerate(id);
      router.push(`/${locale}/dashboard/briefings/${newBriefing.id}`);
    } catch (e) {
      setError(t("common.actionError"));
      setRegenerating(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="rounded-xl border border-clay-100 bg-clay-50 p-4 text-clay-700">{error}</div>
      </main>
    );
  }

  if (!briefing) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <BriefingLoading title={t("common.loading")} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-4 flex items-center justify-between gap-3 text-sm text-ink-soft">
        <div>
          {t("briefing.statusLabel")} <strong className="text-pine-800">{t(`briefing.status.${briefing.status}`)}</strong>
          {briefing.status === "processing" && (
            <span className="ml-2">— {t("briefing.polling")}</span>
          )}
        </div>
        {briefing.status === "ready" && (
          <div className="flex gap-2">
            <a
              href={sharing.pdfUrl(briefing.id)}
              target="_blank"
              rel="noopener"
              className="ad-btn ad-btn-ghost px-3 py-1.5 text-xs"
            >
              <FileDown className="h-3.5 w-3.5" strokeWidth={2} />
              PDF
            </a>
            <button
              type="button"
              onClick={() => setShowShare(true)}
              className="ad-btn ad-btn-primary px-3 py-1.5 text-xs"
            >
              <Share2 className="h-3.5 w-3.5" strokeWidth={2} />
              {t("briefing.share.button")}
            </button>
          </div>
        )}
      </div>

      {briefing.is_stale && (
        <StaleBanner onRegenerate={handleRegenerate} disabled={regenerating} />
      )}

      {briefing.status === "processing" && !timedOut && (
        <BriefingLoading title={t("briefing.generatingTitle")} />
      )}

      {briefing.status === "processing" && timedOut && (
        <div className="mb-4 rounded-xl border border-clay-100 bg-clay-50 p-4 text-sm text-clay-700">
          <p className="font-medium">{t("briefing.timeout.title")}</p>
          <p className="mt-1 text-clay-700/90">{t("briefing.timeout.body")}</p>
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={regenerating}
            className="ad-btn ad-btn-accent mt-3 px-3 py-1.5 text-xs font-medium"
          >
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={2.2} />
            {t("briefing.regenerate")}
          </button>
        </div>
      )}

      {briefing.status === "failed" && (
        <div className="mb-4 rounded-xl border border-clay-100 bg-clay-50 p-4 text-sm text-clay-700">
          <p className="font-medium">{t("briefing.failure.title")}</p>
          <p className="mt-1 text-clay-700/90">{t("briefing.failure.body")}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleRegenerate}
              disabled={regenerating}
              className="ad-btn ad-btn-accent px-3 py-1.5 text-xs font-medium"
            >
              <RefreshCw className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("briefing.regenerate")}
            </button>
            <Link
              href={`/${locale}/dashboard/upload`}
              className="ad-btn ad-btn-ghost px-3 py-1.5 text-xs font-medium"
            >
              <Upload className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("briefing.failure.uploadMore")}
            </Link>
          </div>
        </div>
      )}

      {briefing.status === "ready" && (
        <BriefingDetail briefing={briefing} locale={locale} />
      )}

      {showShare && briefing.status === "ready" && (
        <ShareDialog briefingId={briefing.id} onClose={() => setShowShare(false)} />
      )}
    </main>
  );
}

function BriefingLoading({ title }: { title: string }) {
  const t = useTranslations();
  // A live elapsed counter reassures on slow connections that work is ongoing
  // (not frozen) — the mom-QA pass flagged the bare spinner as anxiety-inducing.
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="ad-card space-y-4 p-5" aria-live="polite">
      <div className="flex items-center gap-3">
        <span
          className="h-6 w-6 shrink-0 animate-spin rounded-full border-2 border-pine-200 border-t-pine-600"
          role="status"
          aria-label={title}
        />
        <div>
          <p className="text-sm font-medium text-ink">{title}</p>
          <p className="text-sm text-ink-soft">
            {t("briefing.generatingPatience")} · {secs}s
          </p>
        </div>
      </div>
      <div className="ad-rise space-y-3">
        <div className="h-3.5 w-1/3 rounded bg-surface-2" />
        <div className="space-y-2.5">
          <div className="h-3 w-full rounded bg-surface-2" />
          <div className="h-3 w-11/12 rounded bg-surface-2" />
          <div className="h-3 w-9/12 rounded bg-surface-2" />
        </div>
        <div className="h-3.5 w-1/4 rounded bg-surface-2" />
        <div className="space-y-2.5">
          <div className="h-3 w-10/12 rounded bg-surface-2" />
          <div className="h-3 w-8/12 rounded bg-surface-2" />
        </div>
      </div>
    </div>
  );
}
