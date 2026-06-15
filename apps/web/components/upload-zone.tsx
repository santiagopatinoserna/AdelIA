"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { UploadCloud, Loader2 } from "lucide-react";

export function UploadZone({ locale }: { locale: string }) {
  const t = useTranslations("upload");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      // Same-origin proxy signs the request server-side — the JWT never
      // reaches the browser (invariant since the api split).
      const res = await fetch("/api/backend/documents", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      // No router.refresh() — dashboard fetches with cache: "no-store"
      router.push(`/${locale}/dashboard`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const f = e.dataTransfer.files[0];
        if (f) upload(f);
      }}
      className="ad-card rounded-2xl border-2 border-dashed border-line-strong bg-surface-2/60 px-6 py-16 text-center transition-colors hover:border-pine-200"
    >
      <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-50 text-pine-400 ring-1 ring-pine-100">
        <UploadCloud className="h-7 w-7" strokeWidth={1.8} />
      </span>
      <p className="mt-5 text-ink-soft">{t("drop")}</p>
      <p className="mt-1 text-sm text-ink-faint">{t("or")}</p>
      <label className="ad-btn ad-btn-primary mt-5 inline-flex cursor-pointer px-5 py-2.5 text-sm">
        {t("browse")}
        <input
          type="file"
          accept="application/pdf,image/png,image/jpeg,audio/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
          }}
        />
      </label>
      {busy && (
        <p className="mt-4 flex items-center justify-center gap-1.5 text-honey-600">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
          {t("uploading")}
        </p>
      )}
      {error && <p className="mt-4 text-clay-600">{error}</p>}
    </div>
  );
}
