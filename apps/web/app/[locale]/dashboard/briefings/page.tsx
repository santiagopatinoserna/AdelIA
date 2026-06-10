import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Link } from "@/lib/navigation";
import { getTranslations } from "next-intl/server";

import { briefings as briefingsApi } from "@/lib/api-client";
import type { BriefingOut } from "@/lib/briefing-types";
import { BriefingList } from "@/components/briefing/briefing-list";

interface Props {
  params: Promise<{ locale: string }>;
}

export default async function BriefingsPage({ params }: Props) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const t = await getTranslations();
  let list: BriefingOut[] = [];
  try {
    list = await briefingsApi.list();
  } catch {
    list = [];
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("briefing.title")}</h1>
        <Link
          href="/dashboard/briefings/new"
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
        >
          {t("briefing.newButton")}
        </Link>
      </div>
      <BriefingList briefings={list} locale={locale} />
    </main>
  );
}
