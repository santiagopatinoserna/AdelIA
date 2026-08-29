// Pass-through root layout. Next needs a root layout for app/not-found.tsx
// to build; the real <html>/<body> (fonts, lang, provider) stay in
// app/[locale]/layout.tsx.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
