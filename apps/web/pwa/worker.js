/* Generated with an exact production build asset allowlist. No data caches. */
const CONFIG = __TIRE_PWA_CONFIG__;
const CACHE_PREFIX = "tire-shell-";
const CACHE_NAME = CACHE_PREFIX + CONFIG.version;
const ASSETS = new Set(CONFIG.assets);

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(CONFIG.assets.map(url => new Request(url, { cache: "reload", credentials: "omit" })));
    } catch (error) {
      await caches.delete(CACHE_NAME);
      throw error;
    }
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", event => {
  if (event.data?.type === "ACTIVATE_UPDATE") event.waitUntil(self.skipWaiting());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  // A closed allowlist excludes API, evidence, auth, RSC and query-string data.
  if (request.method !== "GET" || url.origin !== self.location.origin || url.search
      || request.headers.has("RSC") || request.headers.has("Next-Router-State-Tree")
      || !ASSETS.has(url.pathname)) return;
  if (url.pathname === "/") {
    if (request.mode !== "navigate") return;
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response.ok) return response; // Never put navigation responses in cache.
      } catch { /* Static build shell can be shown; API requests remain network-only. */ }
      const cache = await caches.open(CACHE_NAME);
      const shell = await cache.match("/");
      if (!shell) return Response.error();
      const html = (await shell.text()).replace("</head>", '<meta name="tire-offline-shell" content="true"></head>');
      return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
    })());
    return;
  }
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    return await cache.match(url.pathname) || fetch(request);
  })());
});
