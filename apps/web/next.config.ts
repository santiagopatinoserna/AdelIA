import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./lib/i18n.ts");
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // pg is Node-only; keep it out of webpack bundles (auth adapter uses it)
  serverExternalPackages: ["pg"],
};
export default withNextIntl(nextConfig);
