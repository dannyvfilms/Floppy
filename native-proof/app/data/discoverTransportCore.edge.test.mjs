import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_MEDIA_OPTIONS,
  cardFromDiscoverItem,
  discoverMediaOptionsFromPayload,
  discoverRowsFromPayload,
  hiddenFromPayload,
} from './discoverTransportCore.js';

test('cardFromDiscoverItem keeps unknown media types on the poster shape', () => {
  const card = cardFromDiscoverItem({ source: 'tmdb', media_id: 5, media_type: 'banana', title: 'X' }, 'row1');
  assert.equal(card.mediaType, 'banana');
  assert.equal(card.shape, 'poster');
  assert.deepEqual(card.lines, []);
  assert.equal(card.cardKey, 'banana-tmdb-5');
  assert.deepEqual(card.identity, {
    mediaType: 'banana', source: 'tmdb', mediaId: '5', title: 'X', image: null,
  });
  assert.deepEqual(card.image, { src: null, fallback: '', source: 'primary' });
  assert.equal(card.altTitle, null);
  assert.equal(card.rating, null);
});

test('cardFromDiscoverItem squares music cards and adds year and taste lines', () => {
  const card = cardFromDiscoverItem({
    media_type: 'music',
    source: 'tidal',
    media_id: 9,
    title: 'Album',
    image: null,
    release_date: '2020-05-01',
    display_score: '0.85',
  }, 'row2', 'match');
  assert.equal(card.shape, 'square');
  assert.deepEqual(card.lines, [{
    join: 'dot',
    parts: [
      { text: '2020', muted: false },
      { text: '85% match', muted: true },
    ],
  }]);
});

test('cardFromDiscoverItem reads ten-point scores and rejects junk scores', () => {
  const tenPoint = cardFromDiscoverItem({
    media_type: 'movie', source: 'tmdb', media_id: 1, title: 'A', final_score: '92',
  }, 'row3', 'match');
  assert.deepEqual(tenPoint.lines[0].parts[0], { text: '92% match', muted: false });
  const junk = cardFromDiscoverItem({
    media_type: 'movie', source: 'tmdb', media_id: 1, title: 'A', final_score: 'abc',
  }, 'row3', 'match');
  assert.deepEqual(junk.lines, []);
  const zero = cardFromDiscoverItem({
    media_type: 'movie', source: 'tmdb', media_id: 1, title: 'A', display_score: 0,
  }, 'row3', 'match');
  assert.deepEqual(zero.lines[0].parts[0], { text: '0% match', muted: false }); // sole part, so not muted
});

test('cardFromDiscoverItem prefers the localized then original title for the alt title', () => {
  assert.equal(
    cardFromDiscoverItem({ source: 's', media_id: 1, title: 'T', localized_title: 'Localized' }, 'r').altTitle,
    'Localized',
  );
  assert.equal(
    cardFromDiscoverItem({ source: 's', media_id: 1, title: 'T', localized_title: 'T', original_title: 'Original' }, 'r').altTitle,
    'Original',
  );
  assert.equal(
    cardFromDiscoverItem({ source: 's', media_id: 1, title: 'T', localized_title: 'T' }, 'r').altTitle,
    null,
  );
});

test('discoverRowsFromPayload drops empty rows and keys rows by media type', () => {
  assert.deepEqual(discoverRowsFromPayload(undefined), []);
  const rows = discoverRowsFromPayload({
    rows: [
      { key: 'top', items: [{ media_type: 'movie', source: 'tmdb', media_id: '1', title: 'A' }] },
      { key: 'empty', items: [] },
      { key: 'stale', is_stale: 1, match_signal: 'x', match_label: 'loved', items: [{ media_type: 'tv', source: 'tmdb', media_id: '2', title: 'B' }] },
    ],
  });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].key, 'top:movie');
  assert.equal(rows[0].title, 'top');
  assert.equal(rows[1].key, 'stale:tv');
  assert.equal(rows[1].isStale, true);
  assert.equal(rows[1].matchSignal, 'x');
  assert.equal(rows[1].items.length, 1);
});

test('discoverMediaOptionsFromPayload falls back to the defaults until the payload arrives', () => {
  assert.equal(discoverMediaOptionsFromPayload(undefined), DEFAULT_MEDIA_OPTIONS);
  assert.equal(discoverMediaOptionsFromPayload({ media_options: [] }), DEFAULT_MEDIA_OPTIONS);
  assert.deepEqual(discoverMediaOptionsFromPayload({ media_options: [{ value: 'movie', label: 'Movies' }] }), [
    { value: 'movie', label: 'Movies' },
  ]);
  assert.deepEqual(DEFAULT_MEDIA_OPTIONS, [
    { value: 'all', label: 'All Media' },
    { value: 'hidden', label: 'Hidden' },
  ]);
});

test('hiddenFromPayload maps dates, null artwork and unknown media types', () => {
  assert.deepEqual(hiddenFromPayload(undefined), []);
  const rows = hiddenFromPayload({
    results: [
      { media_type: 'music', item_id: '9', image: null, hidden_at: 'nope' },
      { item_id: '10', hidden_at: '2026-01-02T00:00:00Z' },
    ],
  });
  assert.equal(rows[0].shape, 'square');
  assert.deepEqual(rows[0].lines, []);
  assert.deepEqual(rows[0].image, { src: null, fallback: '', source: 'primary' });
  assert.equal(rows[0].identity.mediaId, '');
  assert.equal(rows[0].cardKey, 'hidden-9');
  assert.equal(rows[1].mediaType, 'movie');
  assert.equal(rows[1].shape, 'poster');
  assert.equal(rows[1].lines.length, 1);
  assert.equal(rows[1].cardKey, 'hidden-10');
});
