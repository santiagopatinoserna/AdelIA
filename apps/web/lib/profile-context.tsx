"use client";
import { createContext, useContext, useState } from "react";
import type { Profile } from "@/lib/enrichment-types";

type Ctx = { profiles: Profile[]; activeId: string | null; setActiveId: (id: string) => void };
const ProfileCtx = createContext<Ctx>({ profiles: [], activeId: null, setActiveId: () => {} });

// The list comes from the server (dashboard/(paid)/layout.tsx fetches it next
// to the paywall and onboarding checks), NOT from a fetch in a mount effect.
// This provider wraps the Suspense boundary that (paid)/loading.tsx creates
// around every paid page. A setState here on mount re-rendered the provider
// with a new context value while that boundary was still being streamed, and
// a context change above a boundary React has not hydrated yet makes React
// drop the server HTML and client-render the boundary instead. The streamed
// segment and the client render then coexisted in the DOM for a few
// milliseconds: every paid page existed twice, which the e2e suite saw as
// Playwright strict-mode violations on /dashboard and /dashboard/chat about
// once per 300 tests. With the data in the first render nothing updates
// before hydration, and the recorder, upload zone and chat no longer start
// with an empty list for a frame.
export function ProfileProvider({
  children,
  initialProfiles,
}: {
  children: React.ReactNode;
  initialProfiles: Profile[];
}) {
  const [activeId, setActiveId] = useState<string | null>(() => {
    const def = initialProfiles.find((p) => p.is_default) ?? initialProfiles[0];
    return def ? def.id : null;
  });
  return (
    <ProfileCtx.Provider value={{ profiles: initialProfiles, activeId, setActiveId }}>
      {children}
    </ProfileCtx.Provider>
  );
}

export function useActiveProfile() {
  return useContext(ProfileCtx);
}
