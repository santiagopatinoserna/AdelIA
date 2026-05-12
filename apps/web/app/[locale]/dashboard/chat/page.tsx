import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { listChatSessions } from "@/lib/chat-client";
import { ChatPageClient } from "@/components/chat-page-client";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const jwt = (session as { jwt?: string }).jwt ?? "";
  const sessions = await listChatSessions().catch(() => []);
  const t = await getTranslations("chat");

  return (
    <main className="flex h-[calc(100vh-0px)] max-h-screen">
      <ChatPageClient
        initialSessions={sessions}
        jwt={jwt}
        locale={locale}
        titleText={t("title")}
      />
    </main>
  );
}
