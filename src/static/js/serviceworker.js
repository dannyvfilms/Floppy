const APP_SCOPE = new URL(self.registration.scope);
const STATIC_BASE_URL = new URL("static/", APP_SCOPE);
const OFFLINE_URL = new URL("static/offline.html", APP_SCOPE).toString();
const SCOPE_KEY = APP_SCOPE.pathname.replace(/[^a-z0-9]+/gi, "-")
  .replace(/^-|-$/g, "") || "root";
const CACHE_PREFIX = `floppy-${SCOPE_KEY}-`;
const CACHE_NAME = `${CACHE_PREFIX}public-shell-v3`;
const LEGACY_CACHE_NAMES = new Set(["floppy-v2"]);
const PRECACHE_URLS = [
  "static/offline.html",
  "static/css/main.css",
  "static/favicon/site.webmanifest",
  "static/favicon/android-chrome-192x192.png",
  "static/favicon/android-chrome-512x512.png",
  "static/fonts/roboto-flex.woff2",
].map((path) => new URL(path, APP_SCOPE).toString());

function isSameOrigin(url) {
  return url.origin === APP_SCOPE.origin;
}

function isAppNavigation(request, url) {
  return (
    request.method === "GET"
    && request.mode === "navigate"
    && isSameOrigin(url)
    && url.pathname.startsWith(APP_SCOPE.pathname)
    && request.headers.get("HX-Request") !== "true"
  );
}

function isPublicStaticRequest(request, url) {
  return (
    request.method === "GET"
    && isSameOrigin(url)
    && url.pathname.startsWith(STATIC_BASE_URL.pathname)
    && request.headers.get("HX-Request") !== "true"
  );
}

function canCacheStaticResponse(response) {
  return response.ok && response.type === "basic";
}

async function precachePublicFiles() {
  const cache = await caches.open(CACHE_NAME);
  await Promise.allSettled(
    PRECACHE_URLS.map(async (url) => {
      const request = new Request(url, {
        cache: "reload",
        credentials: "same-origin",
      });
      const response = await fetch(request);
      if (!canCacheStaticResponse(response)) {
        throw new Error("A public PWA file could not be cached.");
      }
      await cache.put(request, response);
    }),
  );
}

async function offlineNavigationResponse(event) {
  try {
    const preloadResponse = await event.preloadResponse;
    if (preloadResponse) {
      return preloadResponse;
    }
    return await fetch(event.request);
  } catch (error) {
    const cachedFallback = await caches.match(OFFLINE_URL, {
      ignoreSearch: true,
    });
    if (cachedFallback) {
      return cachedFallback;
    }

    return new Response(
      "Floppy is offline. The Floppy server cannot be reached. Try again after the connection is restored.",
      {
        status: 503,
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": "text/plain; charset=utf-8",
        },
      },
    );
  }
}

async function publicStaticResponse(request) {
  const cache = await caches.open(CACHE_NAME);
  const exactMatch = await cache.match(request);
  if (exactMatch) {
    return exactMatch;
  }

  try {
    const networkResponse = await fetch(request);
    if (canCacheStaticResponse(networkResponse)) {
      await cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const previousVersion = await cache.match(request, {
      ignoreSearch: true,
    });
    if (previousVersion) {
      return previousVersion;
    }
    throw error;
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    precachePublicFiles().then(() => self.skipWaiting()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (isAppNavigation(request, url)) {
    event.respondWith(offlineNavigationResponse(event));
    return;
  }

  if (isPublicStaticRequest(request, url)) {
    event.respondWith(publicStaticResponse(request));
  }
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      if (self.registration.navigationPreload) {
        await self.registration.navigationPreload.enable();
      }

      const cacheNames = await caches.keys();
      await Promise.all(
        cacheNames
          .filter(
            (cacheName) => (
              cacheName !== CACHE_NAME
              && (
                cacheName.startsWith(CACHE_PREFIX)
                || LEGACY_CACHE_NAMES.has(cacheName)
              )
            ),
          )
          .map((cacheName) => caches.delete(cacheName)),
      );

      await self.clients.claim();
    })(),
  );
});
