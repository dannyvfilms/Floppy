import { createSidebarListPinsStore, webSidebarListPinsKey } from './sidebarListPinsCore';

// Same account-specific key and event as the server-rendered sidebar.
const key = scope => webSidebarListPinsKey(scope, globalThis.location?.origin);
const store = createSidebarListPinsStore({
  async read(scope) {
    try { const value = JSON.parse(globalThis.localStorage?.getItem(key(scope)) || '[]'); return Array.isArray(value) ? value : []; }
    catch { return []; }
  },
  async write(scope, pins) {
    globalThis.localStorage.setItem(key(scope), JSON.stringify(pins));
    globalThis.dispatchEvent(new Event('sidebar-lists-changed'));
  },
});
if (typeof globalThis.addEventListener === 'function') {
  globalThis.addEventListener('sidebar-lists-changed', store.refresh);
  globalThis.addEventListener('storage', store.refresh);
}
export const configureSidebarListPins = store.configure;
export const getSidebarListPins = store.get;
export const subscribeSidebarListPins = store.subscribe;
export const toggleSidebarListPin = store.toggle;
export const removeSidebarListPin = store.remove;
