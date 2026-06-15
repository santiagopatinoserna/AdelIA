import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";

import { RefluxQuestionnaire } from "@/components/reflux-questionnaire";

export default async function QuestionnairePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  return <RefluxQuestionnaire />;
}
