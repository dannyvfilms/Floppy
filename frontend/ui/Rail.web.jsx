import React, { useEffect, useRef } from 'react';
import { Rail as SharedRail } from './Rail.jsx';

const interactiveSelector = "button, input, select, textarea, [role='button']";

function scrollNode(ref) {
  const value = ref.current;
  if (!value) return null;
  if (typeof value.getScrollableNode === 'function') return value.getScrollableNode();
  if (typeof value.getNativeScrollRef === 'function') return value.getNativeScrollRef();
  return value.nodeType === 1 ? value : null;
}

function useRailWebBehavior(ref) {
  useEffect(() => {
    const node = scrollNode(ref);
    if (!node) return undefined;

    let drag = null;
    let suppressed = false;
    let suppressionTimer = null;
    const addedTabIndex = !node.hasAttribute('tabindex');
    if (addedTabIndex) node.setAttribute('tabindex', '0');
    node.style.cursor = 'grab';

    function releaseCapture(pointerId) {
      if (typeof node.releasePointerCapture !== 'function') return;
      try {
        if (typeof node.hasPointerCapture !== 'function' || node.hasPointerCapture(pointerId)) {
          node.releasePointerCapture(pointerId);
        }
      } catch (_) {}
    }

    function finishDrag(event) {
      if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
      const { pointerId, moved } = drag;
      drag = null;
      node.style.cursor = 'grab';
      releaseCapture(pointerId);
      if (!moved) return;
      suppressed = true;
      clearTimeout(suppressionTimer);
      suppressionTimer = setTimeout(() => { suppressed = false; }, 0);
    }

    function onPointerDown(event) {
      if (event.pointerType !== 'mouse' || event.button !== 0 || event.isPrimary === false) return;
      const target = event.target;
      if (!target || typeof target.closest !== 'function' || !node.contains(target)) return;
      if (target.closest(interactiveSelector)) return;
      drag = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startScrollLeft: node.scrollLeft || 0,
        moved: false,
      };
      suppressed = false;
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
        node.style.cursor = 'grabbing';
        if (typeof node.setPointerCapture === 'function') {
          try { node.setPointerCapture(event.pointerId); } catch (_) {}
        }
      }
      event.preventDefault();
      node.scrollLeft = drag.startScrollLeft - deltaX;
    }

    function onClick(event) {
      if (!suppressed) return;
      const target = event.target;
      if (!target || !node.contains(target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      suppressed = false;
      clearTimeout(suppressionTimer);
    }

    function onKeyDown(event) {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.target !== node) return;
      event.preventDefault();
      const distance = Math.round((node.clientWidth || 0) * 0.85);
      const delta = event.key === 'ArrowRight' ? distance : -distance;
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (typeof node.scrollBy === 'function') node.scrollBy({ left: delta, behavior: reduced ? 'auto' : 'smooth' });
      else node.scrollLeft += delta;
    }

    function onDragStart(event) {
      if (event.target && node.contains(event.target)) event.preventDefault();
    }

    node.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', finishDrag);
    document.addEventListener('pointercancel', finishDrag);
    document.addEventListener('lostpointercapture', finishDrag);
    document.addEventListener('dragstart', onDragStart);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('blur', finishDrag);

    return () => {
      node.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', finishDrag);
      document.removeEventListener('pointercancel', finishDrag);
      document.removeEventListener('lostpointercapture', finishDrag);
      document.removeEventListener('dragstart', onDragStart);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('blur', finishDrag);
      clearTimeout(suppressionTimer);
      node.style.cursor = '';
      if (addedTabIndex) node.removeAttribute('tabindex');
    };
  }, [ref]);
}

// Native mounts the cards near the window and expo-image caches them, so a fast flick lands on
// artwork that is already there. The browser's own lazy loading only starts a poster when it is
// about to scroll into view, which a fast scroll outruns. So once a row is near the screen, its
// next few screens of posters start loading in order. This waits until every poster on screen has
// loaded first: image loading is first-come, and an early request must never queue ahead of a
// cover a person is waiting for (the first screen measured 1.5 to 2 seconds slower without it).
const WARM_MARGIN = '1200px 0px';
const WARM_SCREENS = 3;
const WARM_LIMIT = 24;
const WARM_POLL_MS = 250;
const WARM_SCROLL_DELAY_MS = 120;

const waiting = new Set();
let pollTimer = null;

function screenSettled() {
  const images = document.querySelectorAll('img.media-card-poster');
  for (let index = 0; index < images.length; index += 1) {
    const image = images[index];
    if (image.complete) continue;
    const box = image.getBoundingClientRect();
    if (box.width > 20 && box.bottom > 0 && box.top < window.innerHeight && box.right > 0 && box.left < window.innerWidth) return false;
  }
  return true;
}

function warmRow(node) {
  const row = node.getBoundingClientRect();
  const reach = row.left + node.clientWidth * (1 + WARM_SCREENS);
  const from = row.left - node.clientWidth;
  let started = 0;
  node.querySelectorAll('img[loading="lazy"]').forEach(image => {
    if (started >= WARM_LIMIT) return;
    const box = image.getBoundingClientRect();
    if (box.left > reach || box.right < from) return;
    started += 1;
    image.loading = 'eager';
  });
}

function flushWarmups() {
  pollTimer = null;
  if (!waiting.size) return;
  if (!screenSettled()) {
    pollTimer = setTimeout(flushWarmups, WARM_POLL_MS);
    return;
  }
  const nodes = [...waiting];
  waiting.clear();
  nodes.forEach(node => { if (node.isConnected) warmRow(node); });
}

function requestWarmup(node) {
  waiting.add(node);
  if (!pollTimer) pollTimer = setTimeout(flushWarmups, 0);
}

function useArtworkWarmup(ref, count) {
  const near = useRef(false);
  useEffect(() => {
    const node = scrollNode(ref);
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    let scrollTimer = null;
    const observer = new IntersectionObserver(entries => {
      near.current = entries.some(entry => entry.isIntersecting);
      if (near.current) requestWarmup(node);
    }, { rootMargin: WARM_MARGIN });
    observer.observe(node);
    const onScroll = () => {
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => { if (near.current) requestWarmup(node); }, WARM_SCROLL_DELAY_MS);
    };
    node.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      observer.disconnect();
      node.removeEventListener('scroll', onScroll);
      clearTimeout(scrollTimer);
      waiting.delete(node);
    };
  }, [ref]);
  // Cards added by load-more are warmed too once the row is already near.
  useEffect(() => {
    const node = scrollNode(ref);
    if (node && near.current) requestWarmup(node);
  }, [ref, count]);
}

export function Rail(props) {
  const scrollRef = useRef(null);
  useRailWebBehavior(scrollRef);
  useArtworkWarmup(scrollRef, props.items?.length || 0);
  return <SharedRail {...props} scrollRef={scrollRef} />;
}
