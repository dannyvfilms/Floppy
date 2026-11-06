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

export function Rail(props) {
  const scrollRef = useRef(null);
  useRailWebBehavior(scrollRef);
  return <SharedRail {...props} scrollRef={scrollRef} />;
}
