// Per-server/account list pins. The adapter owns persistence and notifications.
export function webSidebarListPinsKey(scope, origin) {
  return scope.serverUrl === origin
    ? `floppy:sidebar-lists:${scope.userId}`
    : `floppy:sidebar-lists:${scope.serverUrl}:${scope.userId}`;
}

export function createSidebarListPinsStore(storage) {
  let state = { scope: null, pins: [] };
  let revision = 0;
  let pending = Promise.resolve();
  const listeners = new Set();
  const publish = next => { state = next; listeners.forEach(listener => listener(state)); };
  const sameScope = (a, b) => a?.serverUrl === b?.serverUrl && a?.userId === b?.userId;
  async function configure(scope) {
    const normalized = scope?.serverUrl && scope?.userId
      ? { serverUrl: String(scope.serverUrl).replace(/\/$/, ''), userId: String(scope.userId) } : null;
    const version = ++revision;
    if (!normalized) { publish({ scope: null, pins: [] }); return; }
    publish({ scope: normalized, pins: [] });
    const pins = await storage.read(normalized);
    if (version === revision) publish({ scope: normalized, pins: Array.isArray(pins) ? pins : [] });
  }
  async function change(entry, wanted, scope) {
    if (!scope || !entry?.id || !entry?.name || !entry?.url) throw new Error('The sidebar is not ready.');
    if (!sameScope(scope, state.scope)) throw new Error('The signed-in account changed.');
    const current = await storage.read(scope);
    if (!sameScope(scope, state.scope)) throw new Error('The signed-in account changed.');
    const exists = current.some(item => String(item.id) === String(entry.id));
    const pins = current.filter(item => String(item.id) !== String(entry.id));
    if (wanted ?? !exists) pins.push({ id: String(entry.id), name: entry.name, url: entry.url });
    await storage.write(scope, pins);
    if (sameScope(scope, state.scope)) publish({ scope, pins });
  }
  function enqueue(entry, wanted) {
    const scope = state.scope;
    const operation = pending.then(() => change(entry, wanted, scope));
    pending = operation.catch(() => {});
    return operation;
  }
  async function refresh() {
    const scope = state.scope;
    if (!scope) return;
    const pins = await storage.read(scope);
    if (sameScope(scope, state.scope)) publish({ scope, pins });
  }
  return { configure, toggle: entry => enqueue(entry), remove: entry => enqueue(entry, false), refresh, get: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); } };
}
