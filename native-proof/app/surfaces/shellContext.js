// The page a stack screen is showing, so the header search can follow it like
// the web header does (media type of the current page). Screens set it while
// mounted and clear it on unmount.
let current = null;
const listeners = new Set();

export function setShellPageType(mediaType) {
  const next = mediaType || null;
  if (next === current) return;
  current = next;
  listeners.forEach(listener => listener(current));
}

export function getShellPageType() {
  return current;
}

export function subscribeShellPageType(listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
