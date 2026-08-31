import { useTranslations } from "next-intl";
import { Link } from "@/lib/navigation";
import { Compass, ArrowLeft } from "lucide-react";

export default function NotFound() {
  const t = useTranslations("common");
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      {/* No ad-rise on the root: content starting at opacity 0 never reports FCP. */}
      <div className="ad-card max-w-md p-8 text-center md:p-10">
        <span className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
          <Compass className="h-7 w-7" strokeWidth={1.8} />
        </span>
        <p className="mt-5 font-display text-5xl font-semibold text-ink">404</p>
        <h1 className="mt-3 text-xl text-ink">{t("notFoundTitle")}</h1>
        <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">{t("notFoundBody")}</p>
        <Link href="/" className="ad-btn ad-btn-primary mt-6 px-5 py-2.5 text-sm">
          <ArrowLeft className="h-4 w-4" strokeWidth={2.2} />
          {t("backHome")}
        </Link>
      </div>
    </main>
  );
}
