"use client";
import { enrichment } from "@/lib/api-client-browser";
import { useActiveProfile } from "@/lib/profile-context";

export function ProfileSwitcher() {
  const { profiles, activeId, setActiveId } = useActiveProfile();
  if (profiles.length <= 1) return null;
  return (
    <div className="flex gap-2 overflow-x-auto px-3 py-2">
      {profiles.map((p) => (
        <button key={p.id} onClick={() => { setActiveId(p.id); enrichment.setDefaultProfile(p.id).catch(() => {}); }}
          className={`ad-btn min-h-[36px] whitespace-nowrap ${p.id === activeId ? "ad-btn-primary" : "ad-btn-ghost"}`}>
          {p.display_name}
        </button>
      ))}
    </div>
  );
}
