import { notFound } from "next/navigation";
import { getRequestConfig } from "next-intl/server";

export const locales = ["es"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "es";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = (await requestLocale) ?? defaultLocale;
  if (!locales.includes(requested as Locale)) notFound();
  const locale = requested as Locale;
  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
