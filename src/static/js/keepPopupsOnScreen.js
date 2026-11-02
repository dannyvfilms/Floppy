// Keeps dropdowns, popovers and info tooltips inside the screen when they open.
//
// Alpine reveals a popup by clearing its inline `display: none`. These popups are
// positioned from their button (left-0, right-0 or centered) and have a fixed width,
// so near a screen edge they hang off the page. On a phone that makes the page scroll
// sideways or zoom out. We catch the reveal, measure, and shift the popup back inside
// before the browser paints.
(function () {
  const MARGIN = 8;
  // Measured from far off-screen left: overflow on the right makes a phone browser
  // zoom the page out, and it does not shrink back afterwards.
  const PARKED = 10000;

  function keepInViewport(el) {
    const viewportWidth = document.documentElement.clientWidth;
    // No sliding while we move it: the open animation has its own transition.
    el.style.transition = "none";
    el.style.transform = "translateX(" + -PARKED + "px)";
    const rect = el.getBoundingClientRect();
    const half = el.offsetWidth / 2;
    // The open animation scales the popup (and with it the parked distance), so work
    // from its center and unscaled width.
    const scale = rect.width / el.offsetWidth;
    const center = (rect.left + rect.right) / 2 + PARKED * scale;
    let shift = 0;
    if (half * 2 < viewportWidth - MARGIN * 2) {
      if (center - half < MARGIN) {
        shift = MARGIN - (center - half);
      } else if (center + half > viewportWidth - MARGIN) {
        shift = viewportWidth - MARGIN - (center + half);
      }
    }
    el.style.transform = shift ? "translateX(" + shift + "px)" : "";
    el.getBoundingClientRect(); // apply the move before the transition comes back
    el.style.transition = "";

    // A tooltip arrow keeps pointing at the button it belongs to.
    const arrow = el.querySelector(":scope > .border-t-4");
    if (arrow) {
      const anchor = el.parentElement.getBoundingClientRect();
      const arrowLeft = (anchor.left + anchor.right) / 2 - (center - half + shift);
      arrow.style.left = shift ? arrowLeft + "px" : "";
      arrow.style.right = shift ? "auto" : "";
      arrow.style.translate = shift ? "-50% 0" : "";
    }
  }

  new MutationObserver(function (mutations) {
    for (const mutation of mutations) {
      const el = mutation.target;
      if (!el.hasAttribute("x-show") || el.style.display === "none") {
        continue;
      }
      if (!(mutation.oldValue || "").includes("display: none")) {
        continue;
      }
      if (getComputedStyle(el).position === "absolute") {
        keepInViewport(el);
      }
    }
  }).observe(document.documentElement, {
    subtree: true,
    attributes: true,
    attributeFilter: ["style"],
    attributeOldValue: true,
  });
})();
