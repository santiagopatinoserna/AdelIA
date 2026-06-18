"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { UploadCloud, Loader2, AlertCircle } from "lucide-react";

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

  async function upload(file: File) {
    if (busy) return; // guard against rapid double drops/clicks
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
      // No router.refresh() — dashboard fetches with cache: "no-store"
      router.push(`/${locale}/dashboard`);
    } catch {
      // Never surface raw "Error: status 500" to a parent — friendly + localized.
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!busy) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files[0];
        if (f) upload(f);
      }}
      aria-busy={busy}
      className={`ad-card rounded-2xl border-2 border-dashed px-6 py-16 text-center transition-colors ${
        dragging
          ? "border-pine-400 bg-pine-50/60"
          : "border-line-strong bg-surface-2/60 hover:border-pine-200"
      }`}
    >
      <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-50 text-pine-400 ring-1 ring-pine-100">
        <UploadCloud className="h-7 w-7" strokeWidth={1.8} />
      </span>
      <p className="mt-5 text-ink-soft">{dragging ? t("dropActive") : t("drop")}</p>
      <p className="mt-1 text-sm text-ink-faint">{t("or")}</p>
      <label className="ad-btn ad-btn-primary mt-5 inline-flex cursor-pointer px-5 py-2.5 text-sm aria-disabled:cursor-not-allowed aria-disabled:opacity-50">
        {t("browse")}
        <input
          type="file"
          accept={ACCEPT}
          disabled={busy}
          aria-label={t("browse")}
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
            e.target.value = ""; // allow re-selecting the same file after an error
          }}
        />
      </label>
      <p className="mt-4 text-xs text-ink-faint">{t("hint")}</p>
      {busy && (
        <p className="mt-4 flex items-center justify-center gap-1.5 text-honey-600" role="status">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
          {fileName ? `${t("uploading")} ${fileName}` : t("uploading")}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mx-auto mt-4 flex max-w-sm items-start justify-center gap-1.5 text-sm text-clay-600"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2.2} />
          {error}
        </p>
      )}
    </div>
  );
}
