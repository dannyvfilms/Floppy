import assert from 'node:assert/strict';
import test from 'node:test';
import { createRemoteSettingsActions } from './settingsTransportCore.js';

test('activity transport keeps paging and action writes on the authenticated API', async () => {
  const calls = [];
  const actions = createRemoteSettingsActions(async (path, options) => { calls.push({ path, options }); return {}; });
  await actions.loadImportActivity({ page: 2 });
  await actions.actImportActivity({ path: '/integrations/mal/mapping/ignore', values: { item_id: 9, ignored: false } });
  assert.deepEqual(calls, [
    { path: '/api/v1/imports/activity/', options: { query: { page: 2 } } },
    { path: '/api/v1/imports/activity/', options: { method: 'POST', body: {
      path: '/integrations/mal/mapping/ignore', values: { item_id: 9, ignored: false },
    } } },
  ]);
});
