"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import type { BriefingDetailOut } from "@/lib/briefing-types";

interface Props {
  briefing: BriefingDetailOut;
  locale: string;
}

export function BriefingDetail({ briefing }: Props) {
  const t = useTranslations();
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const handler = (e: Event) => {
      const target = e.target as HTMLElement;
      const ent = target.closest<HTMLElement>("[data-citation-id]");
      if (!ent) return;
      ent.classList.toggle("bg-accent-tint");
      ent.classList.toggle("rounded");
    };
    root.addEventListener("click", handler);
    return () => root.removeEventListener("click", handler);
  }, []);

  if (!briefing.html_render) {
    return <div className="text-ink-soft">{t("briefing.noRender")}</div>;
  }

  return (
    <div className="ad-card overflow-x-auto p-4 sm:p-6">
      <div
        ref={rootRef}
        className="briefing-render prose prose-sm max-w-full prose-table:block prose-table:overflow-x-auto"
        dangerouslySetInnerHTML={{ __html: briefing.html_render }}
      />
    </div>
  );
}
