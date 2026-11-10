// Ownfoil-Plus service worker (served at /sw.js by app.py's service_worker route).
//
// What makes the web UI installable as an app, and keeps it pleasant on a flaky LAN:
//  - static assets (CSS, JS, fonts, icons) come from the network, keeping them in
//    step with the fresh page, and fall back to the cache when it can't be reached;
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
        // Network first. Pages always come fresh from the network, and a cached CSS
        // or JS from an older version used to render the fresh page half-broken "for
        // a while" after every update (mixed versions, misaligned tiles) - exactly
        // what the cache-first order below invites. The cache answers only when the
        // server can't be reached, which keeps the offline story whole.
        event.respondWith(caches.open(CACHE).then(cache =>
            fetch(request).then(response => {
                if (response.ok) cache.put(request, response.clone());
                return response;
            }).catch(() => cache.match(request)))));
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    }
    // Everything else (/api/..., downloads, media): not intercepted.
});
