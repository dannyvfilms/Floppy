import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ADD_COPY_UNAVAILABLE,
  COLLECTION_PAGE_SIZE,
  collectionAddressFor,
  collectionEntriesFromPayload,
  collectionItemsFromPayload,
  copyFieldsFor,
  copyValuesFromCopy,
  customFieldGroupsFromPayload,
  customFilterFromGroups,
  customValuesPayload,
  addressedEntryPayload,
  emptyCopyValues,
  entryPayload,
  hasMoreFromPayload,
  mediaTypeColorsFromPayload,
  totalFromPayload,
} from './collectionTransportCore.js';

test('pagination helpers coerce the total and flag the next page', () => {
  assert.equal(COLLECTION_PAGE_SIZE, 100);
  assert.equal(typeof ADD_COPY_UNAVAILABLE, 'string');
  assert.equal(totalFromPayload({ pagination: { total: '42' } }), 42);
  assert.equal(totalFromPayload({}), null);
  assert.equal(totalFromPayload({ pagination: { total: 'soon' } }), null);
  assert.equal(hasMoreFromPayload({ pagination: { next: 'https://x/?offset=100' } }), true);
  assert.equal(hasMoreFromPayload({}), false);
  assert.equal(hasMoreFromPayload({ pagination: { next: null } }), false);
});

test('media type colors fall back to an empty object', () => {
  assert.deepEqual(mediaTypeColorsFromPayload({ media_type_colors: { movie: '#111111' } }), { movie: '#111111' });
  assert.deepEqual(mediaTypeColorsFromPayload({}), {});
  assert.deepEqual(mediaTypeColorsFromPayload({ media_type_colors: 'nope' }), {});
});

test('collection entries accept bare arrays and drop null rows', () => {
  assert.deepEqual(collectionEntriesFromPayload({ results: [null, { id: 2 }] }), [{ id: 2 }]);
  assert.deepEqual(collectionEntriesFromPayload(undefined), []);
  assert.deepEqual(collectionEntriesFromPayload([{ id: 1 }]), [{ id: 1 }]);
});

test('copy fields fall back to the video catalog for unknown media types', () => {
  assert.ok(copyFieldsFor('manga').some(field => field.label === 'Purchase Price'));
  assert.ok(!copyFieldsFor('manga').some(field => field.label === 'Resolution'));
  assert.ok(copyFieldsFor('strangetype').some(field => field.label === 'Resolution'));
});

test('empty copy values and copy mapping survive missing payloads', () => {
  assert.deepEqual(emptyCopyValues(copyFieldsFor('boardgame')), {
    format: '',
    purchasePrice: '',
    purchaseLocation: '',
    collectedAt: '',
  });
  assert.deepEqual(copyValuesFromCopy(undefined), {
    format: '',
    resolution: '',
    hdr: '',
    is3d: false,
    audioCodec: '',
    audioChannels: '',
    bitrate: '',
    purchasePrice: '',
    purchaseLocation: '',
    collectedAt: '',
  });
  assert.equal(copyValuesFromCopy({ bitrate: 320 }).bitrate, '320');
});

test('collection addressing covers episodes and the addressed types only', () => {
  assert.equal(collectionAddressFor(null), null);
  assert.equal(collectionAddressFor({ source: 'tmdb' }), null);
  assert.equal(collectionAddressFor({ source: 'tmdb', media_id: '5', media_type: 'season' }), null);
  assert.equal(collectionAddressFor({ source: 'tmdb', media_id: '5', media_type: 'anime' }), null);
  assert.deepEqual(
    collectionAddressFor({
      media_type: 'episode', source: 'tmdb', media_id: '10', season_number: 2, episode_number: 5,
    }),
    { path: '/api/v1/media/tv/tmdb/10/2/episodes/5/collection/', query: undefined },
  );
  const movie = collectionAddressFor({
    media_type: 'movie', source: 'tmdb', media_id: '5', library_media_type: 'movie',
  });
  assert.equal(movie.path, '/api/v1/media/movie/tmdb/5/collection/');
  assert.deepEqual(movie.query, { library_media_type: 'movie' });
});

test('entryPayload coerces api values and sends only changed keys', () => {
  assert.deepEqual(entryPayload({}), {});
  assert.deepEqual(
    entryPayload({ format: 'DVD', bitrate: '320', purchasePrice: '' }),
    { media_type: 'DVD', bitrate: 320, purchase_price: null },
  );
  assert.deepEqual(
    entryPayload({ format: 'DVD', resolution: '1080p' }, { format: 'Blu-ray', resolution: '1080p' }),
    { media_type: 'DVD' },
  );
});

test('custom values payload reports clears for emptied and removed keys', () => {
  assert.deepEqual(
    customValuesPayload({ a: 'x', b: '' }, { a: 'y', b: 'old', c: 'keep', d: '' }),
    { a: 'x', b: null, c: null },
  );
  assert.deepEqual(customValuesPayload({}, {}), {});
});

test('custom field groups filter by media type and drop empty groups', () => {
  const payload = {
    groups: [
      {
        id: 1,
        name: 'G',
        fields: [
          { id: 'f1', label: 'L', field_type: 'select', options: ['a'], media_types: ['movie'] },
          { id: 'f2', media_types: ['game'] },
        ],
      },
      { id: 2, fields: [{ id: 'f3', media_types: ['game'] }] },
    ],
  };
  const movieGroups = customFieldGroupsFromPayload(payload, 'movie');
  assert.equal(movieGroups.length, 1);
  assert.deepEqual(movieGroups[0].fields.map(field => field.id), ['f1']);
  assert.equal(movieGroups[0].fields[0].fieldType, 'select');
  const allGroups = customFieldGroupsFromPayload(payload);
  assert.equal(allGroups.length, 2);
  assert.deepEqual(customFieldGroupsFromPayload(undefined, 'movie'), []);
});

test('the shared custom filter prefers the first select then the first checkbox', () => {
  const select = customFilterFromGroups([{
    fields: [{ id: 's1', label: 'Color', fieldType: 'select', options: ['red', 'blue'] }],
  }]);
  assert.deepEqual(select, { id: 's1', label: 'Color', choices: [{ value: 'red', label: 'red' }, { value: 'blue', label: 'blue' }] });
  const checkbox = customFilterFromGroups([{
    fields: [{ id: 'c1', label: 'Signed', fieldType: 'checkbox', options: [] }],
  }]);
  assert.deepEqual(checkbox.choices, [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]);
  assert.equal(customFilterFromGroups([{ fields: [{ id: 't1', fieldType: 'text', options: [] }] }]), null);
  assert.equal(customFilterFromGroups(undefined), null);
});

test('addressed payloads keep only the A/V subset and timestamp plain dates', () => {
  assert.deepEqual(
    addressedEntryPayload({ format: 'DVD', resolution: '', purchasePrice: '9', collectedAt: '2026-01-02' }),
    { media_type: 'DVD', collected_at: '2026-01-02T00:00:00' },
  );
  assert.deepEqual(
    addressedEntryPayload({ format: 'DVD', collectedAt: '2026-01-02T08:00' }),
    { media_type: 'DVD', collected_at: '2026-01-02T08:00' },
  );
  assert.deepEqual(addressedEntryPayload({ purchasePrice: '9' }), {});
});

test('collection items group copies per item and map missing artwork to null', () => {
  const sharedItem = {
    media_type: 'movie', source: 'tmdb', media_id: '5', title: 'Same', image: null,
    release_datetime: '2020-05-01T00:00:00Z',
  };
  const entryA1 = {
    id: 1, item: sharedItem, media_type: 'DVD', score: '8',
    collected_at: '2026-01-02T00:00:00Z', custom_field_values: { a: 1 },
  };
  const entryA2 = {
    id: 2, item: sharedItem, media_type: 'Blu-ray', bitrate: null,
    collected_at: 'not-a-date',
  };
  const entryB = {
    id: 3,
    item: { media_type: 'season', source: 'tmdb', media_id: '9', title: 'Show' },
    media_type: '4K Blu-ray',
  };
  const items = collectionItemsFromPayload({ results: [entryA1, entryA2, entryB] });
  assert.equal(items.length, 2);
  const [first, second] = items;
  assert.equal(first.mediaType, 'movie');
  assert.equal(first.title, 'Same');
  assert.equal(first.image.src, null);
  assert.equal(first.rating, 8);
  assert.equal(first.collectedAt, '2026-01-02');
  assert.equal(first.releaseDate, '2020-05-01');
  assert.equal(first.address.path, '/api/v1/media/movie/tmdb/5/collection/');
  assert.equal(first.copies.length, 2);
  assert.equal(first.copies[1].bitrate, '');
  assert.equal(first.copies[1].collectedAt, '');
  assert.deepEqual(first.customValues, { a: 1 });
  assert.equal(second.address, null);
  assert.equal(second.mediaType, 'season');
  assert.deepEqual(collectionItemsFromPayload(undefined), []);
});
