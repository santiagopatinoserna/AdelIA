import { redirect } from "next/navigation";

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
    data = await ingestion.getTelegramLink();
  } catch (e) {
    error = String(e);
  }

  return <TelegramLinkView data={data} error={error} />;
}
