import test from 'node:test';
import assert from 'node:assert/strict';
import { createRemoteSearchActions } from './searchTransportCore.js';

test('manual entry uses authenticated API and sends selected parent', async () => {
  const calls = [];
  const actions = createRemoteSearchActions(async (...args) => { calls.push(args); return {}; });
  await actions.loadManualOptions();
  await actions.loadParents({ kind: 'tv', query: 'Example' });
  await actions.createManualEntry({ media_type: 'season', parent_tv: 42, season_number: '1' });
  assert.deepEqual(calls, [
    ['/api/v1/search/manual-entry/'],
    ['/api/v1/search/parents/', { query: { kind: 'tv', q: 'Example' } }],
    ['/api/v1/search/manual-entry/', { method: 'POST', body: { media_type: 'season', parent_tv: 42, season_number: '1' } }],
  ]);
});
