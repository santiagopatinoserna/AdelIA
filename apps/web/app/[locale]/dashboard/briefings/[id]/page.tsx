"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { FileDown, Share2 } from "lucide-react";

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

  const fetchBriefing = useCallback(async () => {
    if (!id) return;
    try {
      const b = await briefingsApi.getById(id);
      setBriefing(b);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    fetchBriefing();
  }, [fetchBriefing]);

  useEffect(() => {
    if (!briefing || briefing.status !== "processing") return;
    const interval = setInterval(fetchBriefing, 2000);
    return () => clearInterval(interval);
  }, [briefing, fetchBriefing]);

  async function handleRegenerate() {
    if (!id) return;
    setRegenerating(true);
    try {
      const newBriefing = await briefingsApi.regenerate(id);
      router.push(`/${locale}/dashboard/briefings/${newBriefing.id}`);
    } catch (e) {
      setError(String(e));
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
    return <main className="mx-auto max-w-3xl px-6 py-10 text-ink-soft">{t("common.loading")}</main>;
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

      {briefing.status === "failed" && (
        <div className="mb-4 rounded-xl border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {t("briefing.errorBanner")} {briefing.error_message}
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
