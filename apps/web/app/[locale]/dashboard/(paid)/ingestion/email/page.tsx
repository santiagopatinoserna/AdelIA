import { redirect } from "next/navigation";

import { EmailAliasView } from "@/components/email-alias-view";
import { ingestion, type EmailAliasDTO } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function EmailAliasPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  let data: EmailAliasDTO | null = null;
  let error: string | null = null;
  try {
    data = await ingestion.getEmailAlias();
  } catch (e) {
    error = String(e);
  }

  return <EmailAliasView data={data} error={error} />;
}
