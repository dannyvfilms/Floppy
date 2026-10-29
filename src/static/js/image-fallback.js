// An image that fails to load renders as the browser's broken-image glyph,
// which reads as a bug rather than as missing artwork. Templates only fall back
// to IMG_NONE when the *stored* value is blank, so a poster whose URL is fine
// but whose fetch fails - a provider image-cache miss, or an Audiobookshelf
// server that is offline (#861) - had nothing to catch it.
(function () {
  var placeholder = document.documentElement.dataset.imgNone;
  if (!placeholder) return;

  function applyFallback(img) {
    if (img.dataset.imageFallbackApplied || img.getAttribute("src") === placeholder) return;
    var fallback = img.dataset.imageFallback;
    if (fallback && !img.dataset.imageFallbackTried && fallback !== img.getAttribute("src")) {
      img.dataset.imageFallbackTried = "1";
      img.src = fallback;
      return;
    }
    img.dataset.imageFallbackApplied = "1";
    img.src = placeholder;
  }

  // Image load errors do not bubble; capture them for both initial and HTMX images.
  document.addEventListener("error", function (event) {
    var img = event.target;
    if (img && img.tagName === "IMG") applyFallback(img);
  }, true);

  // YouTube sometimes returns a 120px placeholder with HTTP 200 for a
  // missing max-resolution image. Only inspect images with an explicit backup.
  function checkSmallFallback(img) {
    if (img.dataset.imageFallbackOnSmall && !img.dataset.imageFallbackTried &&
        img.naturalWidth === 120 && img.dataset.imageFallback &&
        img.getAttribute("src") !== img.dataset.imageFallback) {
      applyFallback(img);
    }
  }
  document.addEventListener("load", function (event) {
    var img = event.target;
    if (img && img.tagName === "IMG") checkSmallFallback(img);
  }, true);

  // Catch an image that failed before the listener was installed.
  function sweep() {
    document.querySelectorAll("img").forEach(function (img) {
      if (img.complete && img.naturalWidth === 0 && img.getAttribute("src")) {
        applyFallback(img);
      } else if (img.complete) {
        checkSmallFallback(img);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sweep);
  } else {
    sweep();
  }
})();
