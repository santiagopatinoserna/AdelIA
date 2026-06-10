import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { UploadZone } from "@/components/upload-zone";

export default async function UploadPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);
  const jwt = session.jwt ?? "";
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const t = await getTranslations("upload");
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <div className="mt-8">
        <UploadZone apiUrl={apiUrl} jwt={jwt} locale={locale} />
      </div>
    </main>
  );
}
