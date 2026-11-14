import { ROW_LOOKAHEAD_SCREENS } from './homeRowLoading.js';

// Platform difference: the browser reports row positions with
// IntersectionObserver; native measures rows on scroll (native-proof
// homeRowWatcher.js). Both feed the same shared load decision in HomeShelves.

function scrollParent(node) {
  for (let current = node?.parentElement; current; current = current.parentElement) {
    const { overflowY } = getComputedStyle(current);
    if ((overflowY === 'auto' || overflowY === 'scroll') && current.scrollHeight > current.clientHeight) {
      return current;
    }
  }
  return null;
}

// Returns `watchRow(id, node, onChange)` for HomeShelves, or undefined when the
// browser has no IntersectionObserver (HomeShelves then loads every row).
export function createViewportRowWatcher({ lookahead = ROW_LOOKAHEAD_SCREENS } = {}) {
  if (typeof window === 'undefined' || typeof window.IntersectionObserver !== 'function') return undefined;
  const observers = new Map();
  const watched = new Map();

  function report(node) {
    const entry = watched.get(node);
    if (!entry) return;
    const level = entry.visible ? 'visible' : entry.near ? 'near' : 'far';
    if (level === entry.level) return;
    entry.level = level;
    entry.onChange(level);
  }

  function observersFor(root) {
    if (observers.has(root)) return observers.get(root);
    const margin = `${Math.round(lookahead * 100)}% 0px`;
    const update = flag => entries => entries.forEach(item => {
      const entry = watched.get(item.target);
      if (!entry) return;
      entry[flag] = item.isIntersecting;
      report(item.target);
    });
    const pair = {
      visible: new window.IntersectionObserver(update('visible'), { root }),
      near: new window.IntersectionObserver(update('near'), { root, rootMargin: margin }),
    };
    observers.set(root, pair);
    return pair;
  }

  return function watchRow(_id, node, onChange) {
    if (!node || typeof node.getBoundingClientRect !== 'function') return undefined;
    // Home scrolls with the page today; if a layout puts it in a scrolling
    // panel, the look-ahead margin must apply to that panel.
    const pair = observersFor(scrollParent(node));
    watched.set(node, { onChange, visible: false, near: false, level: null });
    pair.near.observe(node);
    pair.visible.observe(node);
    return () => {
      pair.near.unobserve(node);
      pair.visible.unobserve(node);
      watched.delete(node);
    };
  };
}
