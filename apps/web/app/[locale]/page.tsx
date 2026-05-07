import { useTranslations } from "next-intl";
import { Link } from "@/lib/navigation";

export default function HomePage() {
  const t = useTranslations();
  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-4xl font-semibold tracking-tight">{t("common.appName")}</h1>
      <p className="mt-2 text-slate-600">{t("common.tagline")}</p>
      <p className="mt-8 text-lg">{t("home.hero")}</p>
      <p className="mt-2 text-slate-700">{t("home.subhero")}</p>
      <Link
        href="/dashboard"
        className="mt-8 inline-block rounded-md bg-slate-900 px-5 py-2.5 text-white hover:bg-slate-800"
      >
        {t("home.cta")}
      </Link>
    </main>
  );
}
