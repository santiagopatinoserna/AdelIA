import { redirect } from "@/lib/navigation";

// The demo is no longer a second page: the landing IS the demo (one screen,
// the question first). The route stays alive so old links, the three
// languages' bookmarks and search results land on the form instead of a 404.
// It is out of the sitemap (lib/seo.ts) because the canonical page is "/".
export default async function DemoPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  redirect({ href: "/", locale });
}
