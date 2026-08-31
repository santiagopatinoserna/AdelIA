import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Link } from "@/lib/navigation";
import { getTranslations } from "next-intl/server";
import { Plus } from "lucide-react";

import { briefings as briefingsApi } from "@/lib/api-client";
import type { BriefingOut } from "@/lib/briefing-types";
import { BriefingList } from "@/components/briefing/briefing-list";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "briefing" });
  return { title: t("title") };
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
        <h1 className="text-2xl text-ink">{t("briefing.title")}</h1>
        <Link href="/dashboard/briefings/new" className="ad-btn ad-btn-primary px-4 py-2 text-sm">
          <Plus className="h-4 w-4" strokeWidth={2.4} />
          {t("briefing.newButton")}
        </Link>
      </div>
      <BriefingList briefings={list} locale={locale} />
    </main>
  );
}
