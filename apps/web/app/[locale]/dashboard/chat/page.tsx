import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { listChatSessions } from "@/lib/chat-client";
import { listDocuments } from "@/lib/api-client";
import { ChatPageClient } from "@/components/chat-page-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "chat" });
  return { title: t("title") };
}

export default async function ChatPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const [sessions, docs] = await Promise.all([
    listChatSessions().catch(() => []),
    listDocuments().catch(() => []),
  ]);
  const t = await getTranslations("chat");

  return (
    <main className="flex h-[calc(100dvh-3.5rem)]">
      <ChatPageClient
        initialSessions={sessions}
        locale={locale}
        titleText={t("title")}
        hasDocs={docs.length > 0}
      />
    </main>
  );
}
