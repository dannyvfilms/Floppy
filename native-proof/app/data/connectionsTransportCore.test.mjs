import assert from 'node:assert/strict';
import test from 'node:test';
import {
  connectionsFromPayload,
  createLocalConnectionsActions,
  createRemoteConnectionsActions,
  deviceFromPayload,
} from './connectionsTransportCore.js';

test('empty and malformed payloads map to empty lists', () => {
  assert.deepEqual(connectionsFromPayload(null), { accounts: [], sync: [], conflicts: [] });
  assert.deepEqual(connectionsFromPayload({ sync: [{ id: 1 }] }).sync[0].capabilities, []);
});

test('device lookup needs an application name', () => {
  assert.equal(deviceFromPayload({}), null);
  const device = deviceFromPayload({ user_code: 'ABCD-1234', application: 'Floppy TV', scopes: [{ scope: 'library:read' }] });
  assert.equal(device.application, 'Floppy TV');
  assert.equal(device.scopes[0].label, 'library:read');
});

test('remote actions call connection, conflict and device endpoints', async () => {
  const calls = [];
  const actions = createRemoteConnectionsActions(async (path, options) => { calls.push({ path, options }); return {}; });
  await actions.load();
  await actions.setDirection(4, 'both');
  await actions.setPaused(4, true);
  await actions.resolveConflict(9, false);
  await actions.lookupDevice(' ab-12 ');
  await actions.decideDevice('ab-12', 'approve');
  assert.deepEqual(calls.map(call => `${call.options?.method || 'GET'} ${call.path}`), [
    'GET /api/v1/connections/',
    'POST /api/v1/connections/4/direction/',
    'POST /api/v1/connections/4/pause/',
    'POST /api/v1/sync/conflicts/9/resolve/',
    'GET /api/v1/connections/device/',
    'POST /api/v1/connections/device/',
  ]);
  assert.deepEqual(calls[3].options.body, { watched: false });
  assert.deepEqual(calls[4].options.query, { user_code: 'ab-12' });
});

test('local actions report the reason', async () => {
  assert.equal((await createLocalConnectionsActions('r').load()).reason, 'r');
});
