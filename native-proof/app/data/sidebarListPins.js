import { readLocalSetting, writeLocalSetting } from './localSettings';
import { createSidebarListPinsStore } from './sidebarListPinsCore';

const key = scope => `sidebar-lists:${scope.serverUrl}:${scope.userId}`;
const store = createSidebarListPinsStore({
  async read(scope) {
    try { const value = JSON.parse((await readLocalSetting(key(scope))) || '[]'); return Array.isArray(value) ? value : []; }
    catch { return []; }
  },
  async write(scope, pins) { await writeLocalSetting(key(scope), JSON.stringify(pins)); },
});
export const configureSidebarListPins = store.configure;
export const getSidebarListPins = store.get;
export const subscribeSidebarListPins = store.subscribe;
export const toggleSidebarListPin = store.toggle;
export const removeSidebarListPin = store.remove;
