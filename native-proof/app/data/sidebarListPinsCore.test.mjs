import test from 'node:test';
import assert from 'node:assert/strict';
import { createSidebarListPinsStore, webSidebarListPinsKey } from './sidebarListPinsCore.js';

function memoryStorage() {
  const values = new Map();
  const key = scope => `${scope.serverUrl}|${scope.userId}`;
  return {
    async read(scope) { return structuredClone(values.get(key(scope)) || []); },
    async write(scope, pins) { values.set(key(scope), structuredClone(pins)); },
  };
}

test('same-origin web pins share the existing key; other servers remain isolated', () => {
  assert.equal(webSidebarListPinsKey({ serverUrl: 'https://one.example', userId: '1' }, 'https://one.example'), 'floppy:sidebar-lists:1');
  assert.equal(webSidebarListPinsKey({ serverUrl: 'https://two.example', userId: '1' }, 'https://one.example'), 'floppy:sidebar-lists:https://two.example:1');
});

test('pins persist and remain isolated by server and user', async () => {
  const storage = memoryStorage();
  const store = createSidebarListPinsStore(storage);
  const a = { serverUrl: 'https://one.example/', userId: '1' };
  const entry = { id: '4', name: 'Favorites', url: '/list/favorites' };
  await store.configure(a);
  await store.toggle(entry);
  assert.deepEqual(store.get().pins, [entry]);
  await store.configure({ serverUrl: 'https://one.example', userId: '2' });
  assert.deepEqual(store.get().pins, []);
  await store.configure({ serverUrl: 'https://two.example', userId: '1' });
  assert.deepEqual(store.get().pins, []);
  await store.configure(a);
  assert.deepEqual(store.get().pins, [entry]);
  await store.remove(entry);
  await store.configure(a);
  assert.deepEqual(store.get().pins, []);
});

test('queued pin cannot be applied to an account selected later', async () => {
  const storage = memoryStorage();
  const store = createSidebarListPinsStore(storage);
  await store.configure({ serverUrl: 'https://one.example', userId: '1' });
  const pending = store.toggle({ id: '4', name: 'Favorites', url: '/list/4' });
  await store.configure({ serverUrl: 'https://one.example', userId: '2' });
  await assert.rejects(pending, /account changed/);
  assert.deepEqual(store.get().pins, []);
});
