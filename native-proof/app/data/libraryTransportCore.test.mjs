import assert from 'node:assert/strict';
import test from 'node:test';
import {
  libraryPath,
  libraryQuery,
  mediaCardModelFromRow,
  mediaRowsFromPayload,
  createRemoteLibraryActions,
} from './libraryTransportCore.js';

test('library query maps filter-bar state to the shared API filter contract', () => {
  assert.deepEqual(libraryQuery({
    mediaType: 'all', limit: 30, offset: 30, search: 'orbit',
    statuses: ['completed', 'no_status'], sort: 'date_added', direction: 'desc',
    ranges: {
      rating: { from: '6', to: '9' },
      dateAdded: { within: '3', unit: 'weeks' },
    },
    fields: { genre: 'Drama', year: '2024', selectedTags: ['favorite'] },
    modes: { tags: 'and' },
  }), {
    limit: 30, offset: 30, media_type: 'all', search: 'orbit',
    status: ['completed', 'no_status'], sort: 'date_added', direction: 'desc',
    rating_min: '6', rating_max: '9', date_added_within: '3',
    date_added_within_unit: 'weeks', genre: 'Drama', year: '2024',
    tags: ['favorite'], tag_mode: 'and',
  });
});

test('library path uses the all-media endpoint for the all type', () => {
  assert.equal(libraryPath('all'), '/api/v1/media/');
  assert.equal(libraryPath('movie'), '/api/v1/media/movie/');
  assert.equal(libraryPath('music', 'artists'), '/api/v1/music/artists/');
  assert.equal(libraryPath('comic', 'issues'), '/api/v1/media/comicissue/');
});

test('payload rows retain real tracker identity and map to card shapes', () => {
  const [row] = mediaRowsFromPayload({ results: [{
    id: 42, item_id: 42, tracked: true, status: 1, score: 8,
    progress: 4, episodes_left: 6, progress_unit: 'episodes',
    item: { media_type: 'tv', library_media_type: 'tv', source: 'tmdb', media_id: '99',
      title: 'The Quiet Orbit', image: 'https://example.test/poster.jpg', release_datetime: '2024-01-01' },
  }] });
  const card = mediaCardModelFromRow(row.media);
  assert.equal(row.identity.mediaId, '99');
  assert.equal(card.shape, 'poster');
  assert.equal(card.title, 'The Quiet Orbit');
  assert.equal(card.progressBar.percent, 40);
  assert.equal(card.rating.value, 8);
});

test('card projection keeps missing artwork, score and progress nullable', () => {
  const card = mediaCardModelFromRow({ item: { media_type: 'music', title: 'Untitled' }, tracked: false });
  assert.equal(card.shape, 'square');
  assert.equal(card.image.src, null);
  assert.equal(card.rating, null);
  assert.equal(card.progressBar, null);
});

test('native library writes use scoped bulk endpoints and preserve item identity', async () => {
  const calls = [];
  const transport = createRemoteLibraryActions(async (path, options) => {
    calls.push({ path, options });
    return { operation_id: 'op-1' };
  });
  const rows = [{ identity: { itemId: 7 } }, { identity: { itemId: 9 } }];
  await transport.bulkCollection({ rows });
  await transport.bulkAddToList({ listId: 12, rows });
  await transport.startBulkPlays({ rows, options: { scope: 'aired' }, dryRun: true });
  assert.deepEqual(calls.map(call => [call.path, call.options.json]), [
    ['/api/v1/library/bulk/collection/', { item_ids: [7, 9] }],
    ['/api/v1/lists/12/items/bulk/', { item_ids: [7, 9] }],
    ['/api/v1/library/bulk/plays/', { item_ids: [7, 9], options: { scope: 'aired' }, dry_run: true }],
  ]);
});
