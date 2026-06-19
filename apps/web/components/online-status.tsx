"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { WifiOff, Wifi } from "lucide-react";

// Surfaces connectivity loss — parents use this in clinics with spotty wifi,
// where chat/features silently fail otherwise. A clay pill while offline; a
// brief pine "back online" when it returns.
export function OnlineStatus() {
  const t = useTranslations("connectivity");
  const [online, setOnline] = useState(true);
  const [reconnected, setReconnected] = useState(false);

  useEffect(() => {
    setOnline(navigator.onLine);
    const goOffline = () => {
      setOnline(false);
      setReconnected(false);
    };
    const goOnline = () => {
      setOnline(true);
      setReconnected(true);
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  useEffect(() => {
    if (!reconnected) return;
    const id = setTimeout(() => setReconnected(false), 5000);
    return () => clearTimeout(id);
  }, [reconnected]);

  if (online && !reconnected) return null;

  return (
    <div
      role={online ? "status" : "alert"}
      aria-live={online ? "polite" : "assertive"}
      className={`fixed left-1/2 top-[4.25rem] z-40 flex max-w-[92vw] -translate-x-1/2 items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-white shadow-lift ${
        online ? "bg-pine-600" : "bg-clay-600"
      }`}
    >
      {online ? (
        <>
          <Wifi className="h-4 w-4 shrink-0" strokeWidth={2.2} />
          {t("online")}
        </>
      ) : (
        <>
          <WifiOff className="h-4 w-4 shrink-0" strokeWidth={2.2} />
          <span>
            {t("offline")}
            <span className="font-normal text-white/85"> — {t("offlineBody")}</span>
          </span>
        </>
      )}
    </div>
  );
}
