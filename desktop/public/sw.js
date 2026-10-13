// Katha service worker — caches the APP SHELL only.
//
// Katha is online-only by design: every byte of prose lives on the Pi and is
// fetched live from /api. So this worker NEVER caches /api — it only keeps the
// built shell (index.html + hashed assets + icons) so the installed app
// launches instantly and shows *something* if the Pi is briefly unreachable.
//
// No build step, no hashed-asset manifest needed: assets are filled into the
// cache on first use (they're immutable, so cache-first is safe).

const CACHE = 'katha-shell-v2'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(['/'])).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  // Same-origin only, and never touch the live data API.
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  // Navigations: network-first (fresh shell), fall back to the cached shell.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put('/', copy))
          return res
        })
        .catch(() => caches.match('/'))
    )
    return
  }

  // Static assets: cache-first, filling the cache on first use.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(CACHE).then((c) => c.put(request, copy))
          }
          return res
        })
    )
  )
})
