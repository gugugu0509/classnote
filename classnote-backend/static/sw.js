const CACHE = 'classnote-v6';
const URLS = ['/app/', '/app/manifest.json', '/app/icon-192.png', '/app/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(URLS)));
});

self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
