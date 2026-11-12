import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  createRemoteDiscoverActions,
  discoverMediaOptionsFromPayload,
  discoverRowsFromPayload,
  hiddenFromPayload,
} from './discoverTransportCore.js';

const item = (type, id, extra = {}) => ({
  media_type: type, source: 'tmdb', media_id: id, title: `T${id}`, image: 'http://x/a.jpg',
  release_date: '2020-05-01', display_score: 0.82, ...extra,
});

test('rows keep every server row and key repeated All-tab rows apart', () => {
  const rows = discoverRowsFromPayload({
    rows: [
      { key: 'trending_right_now', title: 'TV Shows: Trending', why: 'w', items: [item('tv', 1)] },
      { key: 'trending_right_now', title: 'Movies: Trending', why: 'w', items: [item('movie', 2)] },
      { key: 'empty', title: 'Empty', items: [] },
      ...Array.from({ length: 6 }, (_, i) => ({ key: `r${i}`, title: `R${i}`, items: [item('book', 10 + i)] })),
    ],
  });
  assert.equal(rows.length, 8);
  assert.equal(new Set(rows.map(row => row.key)).size, 8);
});

test('cards carry an identity, the server match wording and the match signal', () => {
  const [row] = discoverRowsFromPayload({
    rows: [{ key: 'top_picks_for_you', match_label: 'Taste match', match_signal: 'Because X',
      title: 'Top', items: [item('movie', 7)] }],
  });
  assert.equal(row.matchSignal, 'Because X');
  const card = row.items[0];
  assert.equal(card.identity.mediaId, '7');
  assert.deepEqual(card.lines[0].parts.map(part => part.text), ['2020', '82% Taste match']);
});

test('rows without match wording show only the year', () => {
  const [row] = discoverRowsFromPayload({ rows: [{ key: 'k', title: 'K', items: [item('movie', 7)] }] });
  assert.deepEqual(row.items[0].lines[0].parts.map(part => part.text), ['2020']);
});

test('hidden entries keep artwork and identity', () => {
  const [entry] = hiddenFromPayload({ results: [{
    item_id: 5, title: 'Hid', media_type: 'movie', source: 'tmdb', media_id: '9',
    image: 'http://x/h.jpg', hidden_at: '2026-01-02T00:00:00Z',
  }] });
  assert.equal(entry.image.src, 'http://x/h.jpg');
  assert.equal(entry.identity.mediaId, '9');
  assert.equal(entry.itemId, 5);
});

test('media options come from the server, with a minimal fallback', () => {
  const options = discoverMediaOptionsFromPayload({ media_options: [
    { value: 'all', label: 'All Media' }, { value: 'tv', label: 'TV Shows' }, { value: 'hidden', label: 'Hidden' }] });
  assert.equal(options.length, 3);
  assert.equal(discoverMediaOptionsFromPayload({}).length, 2);
});

test('hide sends the identity with title and image, status polls the tab', async () => {
  const calls = [];
  const actions = createRemoteDiscoverActions((path, options) => { calls.push([path, options]); return Promise.resolve({}); });
  await actions.hide({ identity: { mediaType: 'movie', source: 'tmdb', mediaId: '7' }, title: 'T', image: 'i' });
  await actions.loadStatus({ mediaType: 'tv', showMore: true });
  assert.deepEqual(calls[0][1].body, {
    action: 'hide', source: 'tmdb', media_type: 'movie', media_id: '7', title: 'T', image: 'i' });
  assert.deepEqual(calls[1], ['/api/v1/discover/status/', { query: { show_more: 1, media_type: 'tv' } }]);
});

test('a non-JSON 200 (a proxy answering with its page) is a failure, not an empty Discover', async () => {
  const actions = createRemoteDiscoverActions(() => Promise.resolve('<!doctype html>'));
  await assert.rejects(() => actions.loadRows(), /expected data/);
});
