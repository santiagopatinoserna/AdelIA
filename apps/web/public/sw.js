/* AdelIA service worker, deliberately conservative.
 *
 * Medical data must never be served stale or cached on shared devices, so:
 * - navigations: network (with navigation preload), offline.html as fallback
 * - /api, auth, dashboard data: untouched, always network
 * - immutable build assets (/_next/static) and icons: cache-first
 *
 * Versioning: the page registers /sw.js?v=<build id> (components/sw-register,
 * id minted in next.config.ts). The id names the cache, so a deploy installs
 * a new worker that, once active, deletes every cache of a previous build.
 * The new worker does NOT skip waiting on its own: it waits for the page to
 * send SKIP_WAITING (the user tapped "Actualizar", or the page already runs
 * that build), so a reload never happens under someone's feet, e.g. while a
 * consult is being recorded.
 */
const VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
const CACHE = `adelia-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const PRECACHE_ICONS = [
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-512-maskable.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // The offline page is the one thing this worker is for: a failure here
      // fails the install (the previous worker keeps serving). Icons are
      // best-effort so a missing PNG can never brick the worker.
      await cache.add(new Request(OFFLINE_URL, { cache: "reload" }));
      await Promise.allSettled(
        PRECACHE_ICONS.map((url) => cache.add(new Request(url, { cache: "reload" })))
      );
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key.startsWith("adelia-") && key !== CACHE)
          .map((key) => caches.delete(key))
      );
      // Navigation preload: the browser starts the navigation request in
      // parallel with the worker's startup instead of after it.
      if (self.registration.navigationPreload) {
        await self.registration.navigationPreload.enable();
      }
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigations: network, falling back to the offline page (and only there:
  // a page is never served from cache).
  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          const preloaded = await event.preloadResponse;
          if (preloaded) return preloaded;
          return await fetch(request);
        } catch {
          const cache = await caches.open(CACHE);
          return (await cache.match(OFFLINE_URL)) || Response.error();
        }
      })()
    );
    return;
  }

  // Immutable build assets + icons: cache-first, in this build's cache.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE);
        const hit = await cache.match(request);
        if (hit) return hit;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })()
    );
  }
  // Everything else (/api, auth, dashboard data): default network behaviour,
  // never cached.
});
