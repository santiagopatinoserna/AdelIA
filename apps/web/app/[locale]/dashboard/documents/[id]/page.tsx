import { auth } from "@/lib/auth";
import { notFound, redirect } from "next/navigation";
import { getDocument } from "@/lib/api-client";
import { StatusBadge } from "@/components/status-badge";

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

  const fileName = doc.s3_key.split("/").pop() ?? doc.s3_key;
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <div className="flex items-center justify-between">
        <h1 className="truncate text-2xl font-semibold">{fileName}</h1>
        <StatusBadge status={doc.status} />
      </div>
      <p className="mt-2 text-sm text-slate-500">
        {new Date(doc.created_at).toLocaleString()}
      </p>
      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6">
        {doc.raw_text ? (
          <pre className="whitespace-pre-wrap font-sans text-sm text-slate-800">{doc.raw_text}</pre>
        ) : (
          <p className="text-slate-400">[ Procesando OCR… recarga en unos segundos ]</p>
        )}
      </section>
    </main>
  );
}
