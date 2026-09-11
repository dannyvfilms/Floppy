(function () {
  if (typeof window === "undefined" || window.__floppyHorizontalDragBound) {
    return;
  }
  window.__floppyHorizontalDragBound = true;

  const rowSelector = '[data-horizontal-drag="true"]';
  let drag = null;
  let suppressedSurface = null;
  let suppressionTimer = null;

  function finishDrag(event) {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) {
      return;
    }

    const { pointerId, surface, moved } = drag;
    drag = null;
    surface.classList.remove("is-horizontal-dragging");
    if (typeof surface.releasePointerCapture === "function") {
      try {
        if (typeof surface.hasPointerCapture !== "function" || surface.hasPointerCapture(pointerId)) {
          surface.releasePointerCapture(pointerId);
        }
      } catch (_) {}
    }

    if (moved) {
      suppressedSurface = surface;
      clearTimeout(suppressionTimer);
      suppressionTimer = setTimeout(() => {
        suppressedSurface = null;
      }, 0);
    }
  }

  function onPointerDown(event) {
    if (event.pointerType !== "mouse" || event.button !== 0 || event.isPrimary === false) return;

    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    if (target.closest("button, input, select, textarea, [role='button']")) return;

    const surface = target.closest(rowSelector);
    if (!surface) return;

    drag = {
      pointerId: event.pointerId,
      surface,
      startX: event.clientX,
      startScrollLeft: surface.scrollLeft || 0,
      moved: false,
    };
    suppressedSurface = null;
    clearTimeout(suppressionTimer);
  }

  function onPointerMove(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (event.buttons === 0) {
      finishDrag(event);
      return;
    }

    const deltaX = event.clientX - drag.startX;
    if (!drag.moved) {
      if (Math.abs(deltaX) <= 6) return;

      drag.moved = true;
      drag.surface.classList.add("is-horizontal-dragging");
      if (typeof drag.surface.setPointerCapture === "function") {
        try {
          drag.surface.setPointerCapture(event.pointerId);
        } catch (_) {}
      }
    }

    event.preventDefault();
    drag.surface.scrollLeft = drag.startScrollLeft - deltaX;
  }

  function onClick(event) {
    if (!suppressedSurface) return;

    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    if (target.closest(rowSelector) !== suppressedSurface) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    suppressedSurface = null;
    clearTimeout(suppressionTimer);
  }

  function onKeyDown(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;

    const target = event.target;
    if (!target || typeof target.closest !== "function") return;

    const surface = target.closest(rowSelector);
    if (!surface || target !== surface) return;

    event.preventDefault();
    const distance = Math.round((surface.clientWidth || 0) * 0.85);
    const delta = event.key === "ArrowRight" ? distance : -distance;
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const behavior = prefersReducedMotion ? "auto" : "smooth";

    if (typeof surface.scrollBy === "function") {
      surface.scrollBy({ left: delta, behavior });
    } else {
      surface.scrollLeft += delta;
    }
  }

  document.addEventListener("pointerdown", onPointerDown);
  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", finishDrag);
  document.addEventListener("pointercancel", finishDrag);
  document.addEventListener("lostpointercapture", finishDrag);
  document.addEventListener("dragstart", event => {
    const target = event.target;
    if (target && typeof target.closest === "function" && target.closest(rowSelector)) {
      event.preventDefault();
    }
  });
  document.addEventListener("click", onClick, true);
  document.addEventListener("keydown", onKeyDown);
  window.addEventListener("blur", finishDrag);
})();
