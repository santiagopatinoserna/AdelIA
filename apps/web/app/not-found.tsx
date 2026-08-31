import Link from "next/link";

import "./globals.css";

// Reached only when the locale layout rejects the first path segment
// (/foo.txt, /favicon.png: dotted paths skip the middleware). There is no
// locale and no messages provider here, so the copy is the default locale's,
// fixed. Without this file Next served its own unbranded English "404".
export default function RootNotFound() {
  return (
    <html lang="es">
      <head>
        <title>404 · AdelIA</title>
      </head>
      <body className="antialiased">
        <main className="flex min-h-screen items-center justify-center px-6 py-16">
          <div className="ad-card max-w-md p-8 text-center md:p-10">
            <p className="font-display text-5xl font-semibold text-ink">404</p>
            <h1 className="mt-3 text-xl text-ink">Página no encontrada</h1>
            <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">
              La página que buscas no existe o se ha movido.
            </p>
            <Link href="/es" className="ad-btn ad-btn-primary mt-6 px-5 py-2.5 text-sm">
              Volver al inicio
            </Link>
          </div>
        </main>
      </body>
    </html>
  );
}
