import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ConsultaRecorder } from "@/components/consulta-recorder";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "consulta.record" });
  return { title: t("title") };
}

export default async function GrabarConsultaPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await auth();
  if (!session) redirect(`/${locale}/signin`);

  return (
    <main className="mx-auto max-w-lg px-6 py-10">
      <ConsultaRecorder />
    </main>
  );
}
