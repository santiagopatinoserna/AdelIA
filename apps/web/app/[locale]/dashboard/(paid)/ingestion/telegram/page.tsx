import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { TelegramLinkView } from "@/components/telegram-link-view";
import { ingestion, type TelegramLinkDTO } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function TelegramLinkPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  let data: TelegramLinkDTO | null = null;
  let error: string | null = null;
  try {
    data = await ingestion.getTelegramLink(locale);
  } catch (e) {
    // 503 = TELEGRAM_BOT_TOKEN not configured on this deployment: say so
    // instead of leaking "ingestion.getTelegramLink: 503".
    const t = await getTranslations({ locale, namespace: "ingestion.telegram" });
    error = /: 503$/.test(String(e)) ? t("notAvailable") : String(e);
  }

  return <TelegramLinkView data={data} error={error} />;
}
