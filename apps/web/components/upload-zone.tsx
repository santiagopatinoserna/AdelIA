"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

export function UploadZone({
  apiUrl,
  jwt,
  locale,
}: {
  apiUrl: string;
  jwt: string;
  locale: string;
}) {
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
      const res = await fetch(`${apiUrl}/documents`, {
        method: "POST",
        body: fd,
        headers: { Authorization: `Bearer ${jwt}` },
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
      className="rounded-lg border-2 border-dashed border-slate-300 bg-white px-6 py-16 text-center"
    >
      <p className="text-slate-600">{t("drop")}</p>
      <p className="mt-1 text-sm text-slate-400">{t("or")}</p>
      <label className="mt-4 inline-block cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800">
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
      {busy && <p className="mt-4 text-amber-700">{t("uploading")}</p>}
      {error && <p className="mt-4 text-rose-700">{error}</p>}
    </div>
  );
}
