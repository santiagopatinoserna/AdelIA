"use client";
import { createContext, useContext, useMemo, useState } from "react";
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

// For a page that has to act when she picks another child, at the moment she
// picks it: "Hoy con <nombre>" is drawn on the server for the default child and
// must ask the API for the new one. The page wraps its subtree, every
// setActiveId below goes through here, and `onSwitch` runs inside her tap's
// own handler. No effect watches activeId, so nothing runs on mount and the
// first render stays the server's (7adb21c). The active child is still the
// ProfileProvider's: this wrapper holds no state, so the recorder, the chat
// and the upload zone keep hearing the same switch.
export function OnProfileSwitch({
  onSwitch,
  children,
}: {
  onSwitch: (id: string) => void;
  children: React.ReactNode;
}) {
  const parent = useContext(ProfileCtx);
  const value = useMemo(
    () => ({
      ...parent,
      setActiveId: (id: string) => {
        const changed = id !== parent.activeId;
        parent.setActiveId(id);
        if (changed) onSwitch(id);
      },
    }),
    [parent, onSwitch],
  );
  return <ProfileCtx.Provider value={value}>{children}</ProfileCtx.Provider>;
}
