// Ownfoil-Plus service worker (served at /sw.js by app.py's service_worker route).
//
// What makes the web UI installable as an app, and keeps it pleasant on a flaky LAN:
//  - static assets (CSS, JS, fonts, icons) are served from a cache and refreshed in
//    the background, so pages paint instantly;
//  - pages always come from the network (they show live data), and fall back to a
//    small "can't reach the server" page when it's unreachable;
//  - the API, game downloads, artwork, uploads and anything not a GET are never
//    touched: they go straight to the server, exactly as without a service worker.
// The cache is named after the app version, so an update drops the old one.

const CACHE = 'ownfoil-plus-{{ version }}';
const PRECACHE = {{ precache | tojson }};

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
    event.waitUntil(caches.keys()
        .then(keys => Promise.all(keys.filter(k => k.startsWith('ownfoil-plus-') && k !== CACHE)
            .map(k => caches.delete(k))))
        .then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== 'GET' || url.origin !== self.location.origin) return;
    if (request.headers.has('range')) return;

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(caches.open(CACHE).then(cache => cache.match(request).then(cached => {
            const fresh = fetch(request).then(response => {
                if (response.ok) cache.put(request, response.clone());
                return response;
            }).catch(() => cached);
            return cached || fresh;
        })));
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    }
    // Everything else (/api/..., downloads, media): not intercepted.
});
