"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { enrichment } from "@/lib/api-client-browser";
import type { Profile } from "@/lib/enrichment-types";

type Ctx = { profiles: Profile[]; activeId: string | null; setActiveId: (id: string) => void };
const ProfileCtx = createContext<Ctx>({ profiles: [], activeId: null, setActiveId: () => {} });

export function ProfileProvider({ children }: { children: React.ReactNode }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  useEffect(() => {
    enrichment.listProfiles().then((ps) => {
      setProfiles(ps);
      const def = ps.find((p) => p.is_default) ?? ps[0];
      setActiveId(def ? def.id : null);
    }).catch(() => setProfiles([]));
  }, []);
  return <ProfileCtx.Provider value={{ profiles, activeId, setActiveId }}>{children}</ProfileCtx.Provider>;
}

export function useActiveProfile() {
  return useContext(ProfileCtx);
}
