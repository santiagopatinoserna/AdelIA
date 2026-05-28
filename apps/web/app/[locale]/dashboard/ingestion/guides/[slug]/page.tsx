"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ingestion } from "@/lib/api-client";
import type { GuideContent } from "@/lib/enrichment-types";

export default function GuideViewerPage() {
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
        <div className="rounded border border-red-300 bg-red-50 p-4 text-red-900">{error}</div>
      </main>
    );
  }

  if (!guide) {
    return <main className="mx-auto max-w-3xl px-6 py-10">Loading…</main>;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{guide.title}</h1>
      <p className="mt-1 text-sm text-slate-600">{guide.description}</p>
      <pre className="mt-6 whitespace-pre-wrap rounded border border-slate-200 bg-white p-6 font-sans text-sm">
        {guide.markdown}
      </pre>
    </main>
  );
}
