import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applyBody,
  candidatesFromPayload,
  previewFromPayload,
  queueFromPayload,
  unmappedRows,
} from './metadataReviewTransportCore.js';

test('queueFromPayload returns empty buckets without a payload', () => {
  assert.deepEqual(queueFromPayload(undefined), { needsReview: [], saved: [] });
  assert.deepEqual(queueFromPayload('nope'), { needsReview: [], saved: [] });
  assert.deepEqual(queueFromPayload({ needs_review: [{ id: 1 }], saved: [] }), {
    needsReview: [{ id: 1 }],
    saved: [],
  });
});

test('candidatesFromPayload maps years and defaults the rest', () => {
  assert.deepEqual(candidatesFromPayload(null), {
    source: null, provider: '', providers: [], query: '', results: [],
  });
  const data = candidatesFromPayload({
    source: 'tmdb',
    provider: 'tmdb',
    providers: ['tmdb'],
    query: 'foo',
    candidates: [
      { media_id: 5, title: 'T', year: 2020, image: 'i.png' },
      { media_id: 5, title: 'T' },
      { media_id: 5, title: 'No image', year: 'x' },
    ],
  });
  assert.equal(data.results[0].id, '5');
  assert.equal(data.results[0].meta, '2020');
  assert.equal(data.results[0].image, 'i.png');
  assert.equal(data.results[1].meta, '');
  assert.equal(data.results[1].image, '');
  // Any truthy year string is shown as-is.
  assert.equal(data.results[2].meta, 'x');
});

test('previewFromPayload needs a token and seeds the mapping from selections', () => {
  assert.equal(previewFromPayload(null), null);
  assert.equal(previewFromPayload({}), null);
  assert.equal(previewFromPayload('nope'), null);
  const preview = previewFromPayload({
    token: 't',
    source: 'a',
    destination: 'b',
    rows: [{ id: 'r1', selected: 'e1' }, { id: 'r2' }],
    episodes: [{ id: 'e1' }],
    reference_count: '4',
  });
  assert.equal(preview.token, 't');
  assert.deepEqual(preview.mapping, { r1: 'e1' });
  assert.equal(preview.referenceCount, 4);
  assert.deepEqual(preview.counts, {});
  assert.deepEqual(preview.scalarConflicts, {});
  assert.equal(preview.rows.length, 2);
  assert.equal(preview.episodes.length, 1);
});

test('applyBody prefers the override mapping and defaults decisions and note', () => {
  const preview = {
    token: 't',
    destination: { id: 9 },
    mapping: { r1: 'e1' },
  };
  assert.deepEqual(applyBody(preview, {}), {
    destination_item_id: 9,
    token: 't',
    mapping: { r1: 'e1' },
    decisions: {},
    note: '',
  });
  assert.deepEqual(applyBody(preview, { mapping: { r2: 'e2' }, note: 'n' }), {
    destination_item_id: 9,
    token: 't',
    mapping: { r2: 'e2' },
    decisions: {},
    note: 'n',
  });
});

test('unmappedRows uses the override mapping and falls back to the preview mapping', () => {
  const preview = {
    token: 't',
    destination: { id: 9 },
    mapping: { r1: 'e1' },
    rows: [{ id: 'r1' }, { id: 'r2' }],
  };
  assert.deepEqual(unmappedRows(preview, { r1: 'e1' }), [{ id: 'r2' }]);
  assert.deepEqual(unmappedRows(preview, null), [{ id: 'r2' }]);
  assert.deepEqual(unmappedRows(preview, {}), [{ id: 'r1' }, { id: 'r2' }]);
});
