"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { UploadCloud, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

import { useActiveProfile } from "@/lib/profile-context";

const MAX_BYTES = 25 * 1024 * 1024; // 25 MB — comfortable for photos, PDFs, voice notes
const ACCEPT = "application/pdf,image/png,image/jpeg,audio/*";

// A mom can drag-drop anything, so validate type + size client-side before
// the upload (the `accept` attr only filters the browse dialog, not drops).
function rejectReason(file: File): "errType" | "errSize" | null {
  const okType =
    file.type === "application/pdf" ||
    file.type === "image/png" ||
    file.type === "image/jpeg" ||
    file.type.startsWith("audio/");
  if (!okType) return "errType";
  if (file.size > MAX_BYTES) return "errSize";
  return null;
}

export function UploadZone({ locale }: { locale: string }) {
  const t = useTranslations("upload");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // Which child this document belongs to. Without it every upload landed with
  // profile_id NULL, so a mother of two filed both children's reports into one
  // undivided pile and the chat answered one child's question out of the
  // other's lab results (audit 4.1, 4.2).
  const { activeId } = useActiveProfile();

  async function upload(file: File) {
    if (busy || done) return; // guard against rapid double drops/clicks
    const reason = rejectReason(file);
    if (reason) {
      setError(t(reason));
      return;
    }
    setBusy(true);
    setError(null);
    setFileName(file.name);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (activeId) fd.append("profile_id", activeId);
      // Same-origin proxy signs the request server-side — the JWT never
      // reaches the browser (invariant since the api split).
      const res = await fetch("/api/backend/documents", {
        method: "POST",
        body: fd,
      });
      if (res.status === 413) {
        setError(t("errSize"));
        return;
      }
      if (!res.ok) throw new Error(`status ${res.status}`);
      // Confirm success and let the mom continue when SHE's ready — show an
      // explicit button. A gentle auto-redirect is only a slow fallback so a
      // distracted parent isn't stranded on this screen.
      setBusy(false);
      setDone(true);
      setTimeout(() => router.push(`/${locale}/dashboard`), 5000);
      return;
    } catch {
      // Never surface raw "Error: status 500" to a parent — friendly + localized.
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }

  // On a phone there is nothing to drag a file onto, so the dashed zone, its
  // icon tile and "Toca para elegir un archivo" only repeated the button
  // (redesign audit, screen 14). From sm up the zone and the drag hint stay.
  return (
    <div>
      <p className="mb-6 text-ink-soft">{t("intro")}</p>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy && !done) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) upload(f);
        }}
        aria-busy={busy}
        className={`ad-card text-center transition-colors max-sm:border-0 max-sm:bg-transparent max-sm:shadow-none sm:rounded-2xl sm:border-2 sm:border-dashed sm:px-6 sm:py-16 ${
          dragging
            ? "border-primary-text bg-primary-tint/60"
            : "border-line-control bg-surface-2/60 hover:border-primary-tint-line"
        }`}
      >
        <span className="mx-auto mb-5 hidden h-14 w-14 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line sm:inline-flex">
          <UploadCloud className="h-7 w-7" strokeWidth={1.8} />
        </span>
        <div>
          <label className="ad-btn ad-btn-primary ad-btn-lg w-full cursor-pointer px-6 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 sm:w-auto">
            <UploadCloud className="h-5 w-5 sm:hidden" strokeWidth={2.2} aria-hidden />
            {t("browse")}
            <input
              type="file"
              accept={ACCEPT}
              disabled={busy || done}
              aria-label={t("browse")}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
                e.target.value = ""; // allow re-selecting the same file after an error
              }}
            />
          </label>
        </div>
        <p className="mt-2 hidden text-ink-soft sm:block">
          {dragging ? t("dropActive") : t("dropDesktop")}
        </p>
        <p className="mt-4 text-sm text-ink-soft">{t("hint")}</p>
        {busy && (
          <p className="mt-4 flex items-center justify-center gap-1.5 text-accent-text" role="status">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
            {fileName ? `${t("uploading")} ${fileName}` : t("uploading")}
          </p>
        )}
        {done && (
          <div className="mt-4 flex flex-col items-center gap-3" role="status">
            <p className="flex items-center gap-1.5 text-primary-text">
              <CheckCircle2 className="h-4 w-4" strokeWidth={2.2} />
              {t("successToast")}
            </p>
            <button
              type="button"
              onClick={() => router.push(`/${locale}/dashboard`)}
              className="ad-btn ad-btn-primary ad-btn-lg w-full px-6 sm:w-auto"
            >
              {t("goDashboard")}
            </button>
          </div>
        )}
        {error && (
          <p
            role="alert"
            className="mx-auto mt-4 flex max-w-sm items-start justify-center gap-1.5 text-sm text-error-text"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2.2} />
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
