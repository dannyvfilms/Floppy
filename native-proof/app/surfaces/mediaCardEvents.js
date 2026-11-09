const listeners = new Set();
const recent = [];
const RECENT_LIMIT = 50;

export function subscribeMediaCardChange(listener) {
  listeners.add(listener);
  recent.forEach(change => listener({ ...change }));
  return () => listeners.delete(listener);
}

export function emitMediaCardChange(change) {
  if (!change) return;
  const detail = { ...change };
  recent.push(detail);
  if (recent.length > RECENT_LIMIT) recent.shift();
  listeners.forEach(listener => listener({ ...detail }));
}
