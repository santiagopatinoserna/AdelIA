import createMiddleware from "next-intl/middleware";
import { locales, defaultLocale } from "./lib/i18n";

export default createMiddleware({
  locales,
  defaultLocale,
  localePrefix: "always",
  // hreflang lives in the <head> of the public pages (lib/seo.ts); the
  // header variant would duplicate it and also tag private dashboard routes.
  alternateLinks: false,
});

export const config = { matcher: ["/((?!api|_next|.*\\..*).*)"] };
