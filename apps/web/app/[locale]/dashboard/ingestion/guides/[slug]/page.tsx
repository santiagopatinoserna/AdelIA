"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { BookOpen } from "lucide-react";

import { ingestion } from "@/lib/api-client-browser";
import type { GuideContent } from "@/lib/enrichment-types";

export default function GuideViewerPage() {
  const tCommon = useTranslations("common");
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? "";
  const [guide, setGuide] = useState<GuideContent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    ingestion
      .getGuide(slug)
      .then(setGuide)
      .catch((e) => setError(String(e)));
  }, [slug]);

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="rounded-lg border border-clay-100 bg-clay-50 p-4 text-clay-700">{error}</div>
      </main>
    );
  }

  if (!guide) {
    return <main className="mx-auto max-w-3xl px-6 py-10">{tCommon("loading")}</main>;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <BookOpen className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {guide.title}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">{guide.description}</p>
      <pre className="mt-6 whitespace-pre-wrap rounded-lg border border-line bg-surface-2 p-6 font-sans text-sm text-ink">
        {guide.markdown}
      </pre>
    </main>
  );
}
