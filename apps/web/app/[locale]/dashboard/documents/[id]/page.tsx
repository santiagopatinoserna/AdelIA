import { notFound, redirect } from "next/navigation";

import { DocumentDetailView } from "@/components/document-detail-view";
import { getDocument } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  let doc;
  try {
    doc = await getDocument(id);
  } catch {
    notFound();
  }

  return <DocumentDetailView initialDoc={doc} locale={locale} />;
}
