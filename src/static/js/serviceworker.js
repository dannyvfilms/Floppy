const CACHE_NAME = "floppy-v2";
const urlsToCache = [
  "/static/css/main.css",
  "/static/favicon/android-chrome-192x192.png",
  "/static/favicon/android-chrome-512x512.png",
  "/static/fonts/roboto-flex.woff2",
];

// Install event
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(urlsToCache);
    }),
  );
  // Activate this worker immediately; don't wait for old one to finish
  self.skipWaiting();
});

// Fetch event
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Only cache same-origin static assets.
  const isSameOrigin = url.origin === self.location.origin;
  const isHtmxRequest = request.headers.get("HX-Request") === "true";

  // Keep app routes and HTMX requests on network to avoid stale dynamic HTML.
  //
  // Return before respondWith. The browser then makes the request on its own
  // network path. Calling respondWith(fetch(request)) here made the worker
  // repeat a request that the browser can do without help. It also replaced
  // the browser offline page with a failed promise, and it stopped navigation
  // preload.
  if (
    request.method !== "GET" ||
    !isSameOrigin ||
    isHtmxRequest ||
    !url.pathname.startsWith("/static/")
  ) {
    return;
  }

  // Cache-first for static assets only.
  event.respondWith(
    caches.match(request).then((response) => {
      if (response) {
        return response;
      }

      return fetch(request)
        .then((networkResponse) => {
          if (networkResponse.ok) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
          }
          return networkResponse;
        })
        .catch(async (error) => {
          // The network is not available. Static URLs contain a file
          // modification time (main.css?1786502224). An exact match fails
          // after each rebuild, because the time changes. Give the previous
          // version instead. A previous version is better than a page that
          // cannot load.
          const previousVersion = await caches.match(request, {
            ignoreSearch: true,
          });
          if (previousVersion) {
            return previousVersion;
          }
          throw error;
        });
    }),
  );
});

// Activate event
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((cacheNames) =>
        Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName !== CACHE_NAME) {
              return caches.delete(cacheName);
            }

            return undefined;
          }),
        ),
      )
      .then(() => self.clients.claim()),
  );
});
