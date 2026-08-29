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

// A question handed over in the URL (?q=...), e.g. from the capability
// showcase on the agent home: sent once on arrival, then removed from the
// URL by the client. Same bound as the API's ChatRequest.question.
const QUESTION_MAX_CHARS = 4000;

function questionFromSearch(q: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(q) ? q[0] : q;
  const text = raw?.trim() ?? "";
  return text ? text.slice(0, QUESTION_MAX_CHARS) : undefined;
}

export default async function ChatPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  const [sessions, docs, { q }] = await Promise.all([
    listChatSessions().catch(() => []),
    listDocuments().catch(() => []),
    searchParams,
  ]);
  const t = await getTranslations("chat");

  // Mobile: header (3.5rem) plus the tab bar (3.5rem), otherwise the input
  // row sat exactly behind the fixed bar until the page was scrolled.
  return (
    <main className="ad-agent-canvas flex h-[calc(100dvh-7rem)] md:h-[calc(100dvh-3.5rem)]">
      <ChatPageClient
        initialSessions={sessions}
        locale={locale}
        titleText={t("title")}
        hasDocs={docs.length > 0}
        initialQuestion={questionFromSearch(q)}
      />
    </main>
  );
}
