// Shared by authenticated and public pages. Keep this in the head so
// remembered artwork is prepared while the document is still being parsed.
(function() {
  // Keep repeat artwork out of the lazy-load queue when an HTMX swap
  // creates new image elements. Remember URLs only; HTTP caching stays
  // with the browser and unseen artwork remains lazy.
  const artworkStorageKey = "floppy-loaded-artwork";
  let rememberedArtwork = [];
  try {
    const saved = JSON.parse(sessionStorage.getItem(artworkStorageKey) || "[]");
    if (Array.isArray(saved)) rememberedArtwork = saved.slice(-256);
  } catch (error) { /* storage disabled */ }
  const loadedArtwork = new Set(rememberedArtwork);
  window.addEventListener("pagehide", function() {
    try {
      sessionStorage.setItem(artworkStorageKey, JSON.stringify([...loadedArtwork]));
    } catch (error) { /* storage disabled */ }
  });

  function promoteArtwork(image, baseUrl, eager = false) {
    let src;
    try {
      src = new URL(image.getAttribute("src"), baseUrl).href;
    } catch (error) {
      return false;
    }
    const warm = loadedArtwork.has(src);
    if (!warm && !eager) return false;
    image.loading = "eager";
    image.decoding = "sync";
    if (warm) image.dataset.artworkReady = "true";
    return true;
  }

  // A regular link creates a new document. Promote remembered posters
  // as the parser inserts them, before the first lazy visibility pass.
  if (document.readyState === "loading") {
    let initialArtworkCount = 0;
    const initialArtworkSeen = new WeakSet();
    function prepareInitialArtwork(image) {
      if (initialArtworkSeen.has(image)) return;
      initialArtworkSeen.add(image);
      promoteArtwork(image, location.href, initialArtworkCount++ < 8);
    }
    const observer = new MutationObserver(function(records) {
      records.forEach(function(record) {
        record.addedNodes.forEach(function(node) {
          if (node.nodeType !== 1) return;
          if (node.matches("img.media-card-poster[src], img[data-media-artwork][src]")) {
            prepareInitialArtwork(node);
          }
          node.querySelectorAll("img.media-card-poster[src], img[data-media-artwork][src]").forEach(prepareInitialArtwork);
        });
      });
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener("DOMContentLoaded", () => observer.disconnect(), { once: true });
  }

  document.addEventListener("load", function(event) {
    const image = event.target;
    if (!image.matches?.("img.media-card-poster, img[data-media-artwork]") || !image.naturalWidth) return;
    const src = image.currentSrc || image.src;
    loadedArtwork.delete(src);
    loadedArtwork.add(src);
    if (loadedArtwork.size > 256) {
      loadedArtwork.delete(loadedArtwork.values().next().value);
    }
  }, true);

  document.addEventListener("htmx:beforeSwap", function(event) {
    const detail = event.detail;
    if (!detail?.xhr || detail.shouldSwap === false) return;
    const xhr = detail.xhr;
    const response = detail.serverResponse || xhr.responseText || "";
    const firstTag = response.match(/<([a-z][^\s/>]*)/i)?.[1].toLowerCase();
    const isDocument = firstTag === "html" || firstTag === "body";
    // Parsing table fragments as documents discards their thead/tbody/tr/td
    // elements. A template preserves them until HTMX swaps into the table.
    const page = isDocument
      ? new DOMParser().parseFromString(response, "text/html")
      : document.createElement("template");
    if (!isDocument) page.innerHTML = response;
    const root = isDocument ? page : page.content;
    let prepared = false;
    root.querySelectorAll("img.media-card-poster[src], img[data-media-artwork][src]").forEach(function(image, index) {
      if (promoteArtwork(image, xhr.responseURL || location.href, index < 8)) prepared = true;
    });
    if (prepared) detail.serverResponse = isDocument ? page.documentElement.outerHTML : page.innerHTML;
  });
})();
