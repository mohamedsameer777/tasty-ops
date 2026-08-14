const CACHE_NAME = 'tasty-zone-shell-v1';
const APP_SHELL = [
  '/static/billing/manifest.json',
  '/static/billing/icons/icon-192.png',
  '/static/billing/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls or non-GET requests — billing/stock/agent data must
  // always be fresh. Let these go straight to the network, no interception.
  if (url.pathname.startsWith('/api/') || event.request.method !== 'GET') {
    return;
  }

  // Page navigations (opening /billing/, /dashboard/, etc.): try the network
  // first so you always get the live page when online; if offline and we've
  // shown this page before in this session, fall back to a simple offline
  // notice rather than a browser error screen.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          '<!DOCTYPE html><html><body style="background:#0f1720;color:#e8edf2;font-family:sans-serif;padding:40px;text-align:center;">' +
          '<h2>You\'re offline</h2><p>Tasty Zone Smart Ops needs an internet connection to load billing and stock data.</p>' +
          '<p>Reconnect and reload this page.</p></body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        )
      )
    );
    return;
  }

  // Static assets (icons, manifest, CSS/JS if any): cache-first, since these
  // rarely change and this is what makes the app feel instant on repeat opens.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      });
    })
  );
});
