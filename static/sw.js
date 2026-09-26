// Simple PWA service worker - avoid caching dynamic attendance traffic
const CACHE = 'smartqr-v1';
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC_ASSETS)).catch(()=>{}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Do NOT cache dynamic attendance or socket.io
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/attendance/') || url.pathname.startsWith('/ws/') || url.pathname.startsWith('/socket.io/')) {
    return; // go to network
  }
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(res => {
      // cache static GETs
      if (res.ok && url.origin === location.origin) {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match(e.request))
  );
});
