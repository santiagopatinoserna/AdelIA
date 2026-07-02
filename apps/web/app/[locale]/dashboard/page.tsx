import { getLocale, getTranslations } from "next-intl/server";
import { Link } from "@/lib/navigation";
import { ProfileProvider } from "@/lib/profile-context";
import { AgentCanvas } from "@/components/agent/agent-canvas";

export default async function DashboardHome() {
  const locale = await getLocale();
  const t = await getTranslations("agent");
  return (
    <ProfileProvider>
      <div className="relative">
        <AgentCanvas locale={locale} />
        <Link href="/dashboard/overview" className="absolute right-3 top-2 text-sm text-ink-faint underline">
          {t("seeAll")}
        </Link>
      </div>
    </ProfileProvider>
  );
}
