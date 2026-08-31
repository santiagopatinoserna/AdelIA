import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { Mic } from "lucide-react";
import { UploadZone } from "@/components/upload-zone";
import { Link } from "@/lib/navigation";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "upload" });
  return { title: t("title") };
}

export default async function UploadPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);
  const t = await getTranslations("upload");
  const tr = await getTranslations({ locale, namespace: "consulta.record" });
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <div className="mt-8">
        <UploadZone locale={locale} />
      </div>
      <Link
        href="/dashboard/consulta/grabar"
        className="mt-6 flex items-center justify-center gap-2 text-sm text-primary-text underline decoration-primary-tint-line underline-offset-2 hover:text-primary-text-hover"
      >
        <Mic className="h-4 w-4" strokeWidth={2} />
        {tr("entryTitle")}
      </Link>
    </main>
  );
}
