"use client";

import { useEffect, useRef } from "react";

import type { BriefingDetailOut } from "@/lib/briefing-types";

interface Props {
  briefing: BriefingDetailOut;
  locale: string;
}

export function BriefingDetail({ briefing }: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const handler = (e: Event) => {
      const target = e.target as HTMLElement;
      const ent = target.closest<HTMLElement>("[data-citation-id]");
      if (!ent) return;
      ent.classList.toggle("bg-honey-100");
      ent.classList.toggle("rounded");
    };
    root.addEventListener("click", handler);
    return () => root.removeEventListener("click", handler);
  }, []);

  if (!briefing.html_render) {
    return <div className="text-ink-soft">No HTML render available.</div>;
  }

  return (
    <div
      ref={rootRef}
      className="briefing-render ad-card p-6"
      dangerouslySetInnerHTML={{ __html: briefing.html_render }}
    />
  );
}
