// Quant Desk service worker: makes the dashboard installable (an app window, a Start-menu / taskbar icon) and shows
// alert and order notifications even when its window is in the background. Deliberately small:
//   - /assets/* (content-hashed build files) are served from a cache, so a reopened app starts instantly;
//   - everything else (the app page, /api, the price stream) always goes to the server: prices, signals and orders are
//     never served from a cache, and a rebuilt app is picked up at once.
const CACHE = 'qd-assets-v1'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k)
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== self.location.origin || !url.pathname.startsWith('/assets/')) return
  e.respondWith((async () => {
    const cache = await caches.open(CACHE)
    const hit = await cache.match(e.request)
    if (hit) return hit
    const res = await fetch(e.request)
    if (res.ok) cache.put(e.request, res.clone())
    return res
  })())
})

// a click on a notification focuses the dashboard (or opens it) on the page the notification points to
self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const path = (e.notification.data && e.notification.data.path) || '/'
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const c of all) {
      if ('focus' in c) { await c.focus(); if ('navigate' in c) await c.navigate(path); return }
    }
    await self.clients.openWindow(path)
  })())
})
