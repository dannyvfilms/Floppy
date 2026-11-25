import assert from 'node:assert/strict';
import { test } from 'node:test';
import { enrichServerCard, musicCreateFromHref, routeCardHref } from './serverCardCore.js';
import { adjustProgressRequest, progressFromResponse } from './homeProgressCore.js';

const card = {
  title: 'Deep Field',
  href: '/dw/details/tmdb/tv/1399/deep-field/season/2/episode/3',
  actions: { items: [{ kind: 'modal', modal: 'track' }, { kind: 'link', href: '/history' }] },
};

test('enrichServerCard derives an identity from the detail URL and hands it to modal actions', () => {
  const next = enrichServerCard(card);
  assert.equal(next.identity.mediaType, 'episode');
  assert.equal(next.identity.mediaId, '1399');
  assert.equal(next.identity.seasonNumber, 2);
  assert.equal(next.actions.items[0].media.source, 'tmdb');
  assert.equal(next.actions.items[1].media, undefined);
});

test('enrichServerCard leaves unaddressable cards untouched', () => {
  const album = { title: 'Album', href: '/details/music/artist/4/x/album/9/y', actions: { items: [] } };
  assert.equal(enrichServerCard(album), album);
  assert.equal(enrichServerCard(null), null);
});

test('routeCardHref opens detail and history links only', () => {
  const calls = [];
  const navigate = (...args) => calls.push(args);
  assert.equal(routeCardHref('/details/tmdb/movie/1/x?next=1', navigate), true);
  assert.equal(routeCardHref('/history?person_id=3', navigate), true);
  assert.equal(routeCardHref('/details/music/artist/4/x/album/9/y', navigate), true);
  assert.equal(routeCardHref('/somewhere', navigate), false);
  assert.deepEqual(calls[0], ['Detail', { href: '/details/tmdb/movie/1/x' }]);
  assert.deepEqual(calls[1], ['History', { filters: 'person_id=3' }]);
  assert.deepEqual(calls[2], ['Music', { artistId: 4, albumId: 9 }]);
});

test('adjustProgressRequest addresses seasons and plain items', () => {
  const [path, options] = adjustProgressRequest(
    { mediaType: 'season', source: 'tmdb', mediaId: '1399', seasonNumber: 2 }, 'increase');
  assert.equal(path, '/api/v1/media/tv/tmdb/1399/2/progress/');
  assert.deepEqual(options, { method: 'POST', body: { operation: 'increase' } });
  assert.equal(
    adjustProgressRequest({ mediaType: 'book', source: 'hardcover', mediaId: 'a b' }, 'decrease')[0],
    '/api/v1/media/book/hardcover/a%20b/progress/');
});

test('progressFromResponse updates the value and bounds', () => {
  const current = { value: '4', canDecrease: true, canIncrease: true };
  assert.deepEqual(progressFromResponse(current, { progress: 10, max_progress: 10 }),
    { value: '10', canDecrease: true, canIncrease: false });
  assert.deepEqual(progressFromResponse(current, { progress: 0 }),
    { value: '0', canDecrease: false, canIncrease: true });
  assert.equal(progressFromResponse(current, null), current);
});

test('musicCreateFromHref reads the provider id from the create route', () => {
  assert.deepEqual(musicCreateFromHref('/dw/music/artist/create/abc-123/'), { kind: 'artist', id: 'abc-123' });
  assert.deepEqual(musicCreateFromHref('/music/album/create/r1/'), { kind: 'album', id: 'r1' });
  assert.equal(musicCreateFromHref('/details/music/artist/4/x'), null);
});
