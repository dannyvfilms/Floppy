import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applyBody,
  candidatesFromPayload,
  createLocalMetadataReviewActions,
  createRemoteMetadataReviewActions,
  previewFromPayload,
  queueFromPayload,
  unmappedRows,
} from './metadataReviewTransportCore.js';

test('queue and candidates tolerate missing fields', () => {
  assert.deepEqual(queueFromPayload(undefined), { needsReview: [], saved: [] });
  const candidates = candidatesFromPayload({ candidates: [{ media_id: 5, title: 'Found', year: 2001 }, { media_id: 6, title: 'No year' }] });
  assert.deepEqual(candidates.results.map(row => [row.id, row.meta]), [['5', '2001'], ['6', '']]);
});

test('preview starts from the suggested numbering and reports unmapped rows', () => {
  const preview = previewFromPayload({
    token: 't',
    destination: { id: 7 },
    rows: [{ id: '1_1', selected: '1:1' }, { id: '1_2', selected: '' }],
    episodes: [{ id: '1:1' }],
    reference_count: 3,
  });
  assert.deepEqual(preview.mapping, { '1_1': '1:1' });
  assert.deepEqual(unmappedRows(preview).map(row => row.id), ['1_2']);
  assert.deepEqual(unmappedRows(preview, { '1_1': 'a', '1_2': 'b' }), []);
  assert.equal(preview.referenceCount, 3);
  assert.equal(previewFromPayload({}), null);
});

test('apply body carries the preview token and chosen destination', () => {
  const preview = previewFromPayload({ token: 't', destination: { id: 7 }, rows: [{ id: '1_1', selected: '1:1' }] });
  assert.deepEqual(applyBody(preview, { note: 'n' }), {
    destination_item_id: 7, token: 't', mapping: { '1_1': '1:1' }, decisions: {}, note: 'n',
  });
});

test('remote actions call the review endpoints', async () => {
  const calls = [];
  const actions = createRemoteMetadataReviewActions(async (path, options) => { calls.push({ path, options }); return {}; });
  const preview = previewFromPayload({ token: 't', destination: { id: 7 } });
  await actions.queue();
  await actions.reference(2, 'ignored');
  await actions.candidates(5, { q: 'a', provider: '' });
  await actions.preview(5, { provider: 'tmdb', q: 'a', destinationMediaId: '9' });
  await actions.apply(5, preview, {});
  assert.deepEqual(calls.map(call => `${call.options?.method || 'GET'} ${call.path}`), [
    'GET /api/v1/metadata-review/',
    'POST /api/v1/metadata-review/references/2/',
    'GET /api/v1/metadata-review/items/5/candidates/',
    'POST /api/v1/metadata-review/items/5/preview/',
    'POST /api/v1/metadata-review/items/5/apply/',
  ]);
  assert.deepEqual(calls[2].options.query, { q: 'a' });
});

test('local actions report the reason', async () => {
  assert.equal((await createLocalMetadataReviewActions('r').queue()).local, true);
});
