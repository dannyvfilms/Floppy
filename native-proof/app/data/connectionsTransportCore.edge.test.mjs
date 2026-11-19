import assert from 'node:assert/strict';
import test from 'node:test';
import {
  connectionsFromPayload,
  deviceFromPayload,
} from './connectionsTransportCore.js';

test('connectionsFromPayload returns empty buckets for absent and non-object payloads', () => {
  assert.deepEqual(connectionsFromPayload(undefined), { accounts: [], sync: [], conflicts: [] });
  assert.deepEqual(connectionsFromPayload('nope'), { accounts: [], sync: [], conflicts: [] });
  assert.deepEqual(connectionsFromPayload(null), { accounts: [], sync: [], conflicts: [] });
});

test('connectionsFromPayload normalizes every sync row with array capabilities', () => {
  const data = connectionsFromPayload({ sync: [{ name: 'binding', direction: 'both' }] });
  assert.deepEqual(data.sync, [{
    name: 'binding',
    direction: 'both',
    capabilities: [],
    direction_choices: [],
  }]);
  assert.deepEqual(connectionsFromPayload({ sync: 'nope' }).sync, []);
});

test('deviceFromPayload needs an application and defaults every optional field', () => {
  assert.equal(deviceFromPayload(undefined), null);
  assert.equal(deviceFromPayload({ user_code: 'ABCD' }), null);
  assert.deepEqual(deviceFromPayload({ application: 'TV' }), {
    userCode: '',
    application: 'TV',
    scopes: [],
  });
});

test('deviceFromPayload maps scope entries with label and description fallbacks', () => {
  const device = deviceFromPayload({
    application: 'Floppy for TV',
    user_code: 'ABCD-EFGH',
    scopes: [{ scope: 'catalog:read' }, { scope: 'lists:write', label: 'Edit lists', description: 'd' }],
  });
  assert.deepEqual(device.scopes, [
    { scope: 'catalog:read', label: 'catalog:read', description: '' },
    { scope: 'lists:write', label: 'Edit lists', description: 'd' },
  ]);
});
