// Minimal service worker: caches the app shell so the installed PWA still
// opens (with whatever data was last loaded) when offline, and always
// prefers the network for the data JSON files so a connected user never
// sees stale coffee data on purpose.
const CACHE_NAME = "origin-shell-v2";
const SHELL_FILES = [
  "./index.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;

  const isData = req.url.endsWith(".json") && !req.url.endsWith("manifest.json");
  if (isData) {
    // Network-first: real data beats a stale cache whenever we're online.
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // App shell: cache-first, so the installed icon opens instantly offline.
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
