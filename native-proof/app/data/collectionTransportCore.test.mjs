import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ADD_COPY_UNAVAILABLE,
  COLLECTION_PAGE_SIZE,
  collectionAddressFor,
  collectionEntriesFromPayload,
  collectionItemsFromPayload,
  collectionQuery,
  copyFieldsFor,
  copyValuesFromCopy,
  customFieldGroupsFromPayload,
  customFilterFromGroups,
  customValuesPayload,
  createLocalCollectionActions,
  createRemoteCollectionActions,
  emptyCopyValues,
  entryPayload,
  addressedEntryPayload,
  hasMoreFromPayload,
  totalFromPayload,
} from './collectionTransportCore.js';

const ENTRY = (id, overrides = {}) => ({
  id,
  media_type: 'Blu-ray',
  resolution: '1080p',
  hdr: 'HDR10',
  is_3d: false,
  audio_codec: 'DTS',
  audio_channels: '5.1',
  bitrate: 320,
  collected_at: '2026-01-02T03:04:05Z',
  item: {
    title: 'Arrival',
    source: 'tmdb',
    media_id: '345942',
    media_type: 'movie',
    image: 'https://img/arrival.jpg',
    release_datetime: '2016-11-09T00:00:00Z',
  },
  ...overrides,
});

test('collectionQuery sends only limit and offset', () => {
  assert.deepEqual(collectionQuery(), { limit: COLLECTION_PAGE_SIZE, offset: 0 });
  assert.deepEqual(collectionQuery({ limit: 5, offset: 100 }), { limit: 5, offset: 100 });
});

test('collectionEntriesFromPayload reads results and plain arrays', () => {
  assert.deepEqual(collectionEntriesFromPayload({ results: [ENTRY(1)] }), [ENTRY(1)]);
  assert.deepEqual(collectionEntriesFromPayload([ENTRY(2)]), [ENTRY(2)]);
  assert.deepEqual(collectionEntriesFromPayload(null), []);
});

test('collectionItemsFromPayload groups copies per item newest first', () => {
  const items = collectionItemsFromPayload({
    results: [ENTRY(1, { collected_at: '2026-02-02T00:00:00Z' }), ENTRY(2, { media_type: 'DVD' })],
  });
  assert.equal(items.length, 1);
  const item = items[0];
  assert.equal(item.id, '1');
  assert.equal(item.mediaType, 'movie');
  assert.equal(item.title, 'Arrival');
  assert.deepEqual(item.identity, { mediaType: 'movie', source: 'tmdb', mediaId: '345942' });
  assert.equal(item.format, 'Blu-ray');
  assert.equal(item.collectedAt, '2026-02-02');
  assert.equal(item.releaseDate, '2016-11-09');
  assert.equal(item.copies.length, 2);
  assert.deepEqual(item.copies.map(copy => copy.id), ['1', '2']);
  assert.equal(item.copies[1].label, 'DVD');
});

test('collectionItemsFromPayload leaves absent columns empty', () => {
  const item = collectionItemsFromPayload({ results: [ENTRY(1)] })[0];
  assert.equal(item.location, '');
  assert.equal(item.rating, null);
  assert.equal(item.completeness, null);
  assert.equal(item.copyLabel, '');
  assert.deepEqual(item.copies[0].purchasePrice, '');
  assert.deepEqual(item.copies[0].purchaseLocation, '');
});

test('collectionItemsFromPayload maps location, rating, completeness and custom values', () => {
  const item = collectionItemsFromPayload({
    results: [ENTRY(1, {
      purchase_location: 'Shelf B',
      purchase_price: '12.50',
      score: 8.5,
      completeness: { collected: 3, total: 10, is_partial: true },
      custom_field_values: { 4: 'Mint' },
    })],
  })[0];
  assert.equal(item.location, 'Shelf B');
  assert.equal(item.rating, 8.5);
  assert.deepEqual(item.completeness, { collected: 3, total: 10, isPartial: true });
  assert.deepEqual(item.customValues, { 4: 'Mint' });
  assert.equal(item.copies[0].purchasePrice, '12.50');
  assert.equal(item.copies[0].purchaseLocation, 'Shelf B');
});

test('custom field helpers scope groups, build the filter and diff values', () => {
  const payload = {
    groups: [{
      id: 1,
      name: 'Condition',
      fields: [
        { id: 4, label: 'Grade', field_type: 'select', options: ['Mint', 'Good'], media_types: ['movie'] },
        { id: 5, label: 'Volume', field_type: 'number', options: [], media_types: ['book'] },
      ],
    }],
  };
  const movie = customFieldGroupsFromPayload(payload, 'movie');
  assert.deepEqual(movie[0].fields.map(field => field.label), ['Grade']);
  assert.deepEqual(customFieldGroupsFromPayload(payload, 'game'), []);
  assert.deepEqual(customFilterFromGroups(movie), {
    id: '4', label: 'Grade', choices: [{ value: 'Mint', label: 'Mint' }, { value: 'Good', label: 'Good' }],
  });
  assert.equal(customFilterFromGroups([]), null);
  assert.deepEqual(customValuesPayload({ 4: 'Good', 6: '' }, { 4: 'Mint', 6: 'x' }), { 4: 'Good', 6: null });
  assert.deepEqual(customValuesPayload({ 4: 'Mint' }, { 4: 'Mint' }), {});
});

test('collectionAddressFor builds the plain route for provider media', () => {
  assert.deepEqual(
    collectionAddressFor({ source: 'tmdb', media_id: '345942', media_type: 'movie' }),
    { path: '/api/v1/media/movie/tmdb/345942/collection/', query: undefined },
  );
  assert.deepEqual(
    collectionAddressFor({ source: 'openlibrary', media_id: 'ol-1', media_type: 'book', library_media_type: 'book' }),
    { path: '/api/v1/media/book/openlibrary/ol-1/collection/', query: { library_media_type: 'book' } },
  );
});

test('collectionAddressFor routes episodes through the tv episode path', () => {
  assert.deepEqual(
    collectionAddressFor({
      source: 'tmdb', media_id: '1668', media_type: 'episode',
      season_number: 2, episode_number: 5, library_media_type: 'anime',
    }),
    {
      path: '/api/v1/media/tv/tmdb/1668/2/episodes/5/collection/',
      query: { library_media_type: 'anime' },
    },
  );
});

test('collectionAddressFor returns null for types the API cannot address', () => {
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'season', season_number: 1 }), null);
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'comic_issue' }), null);
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'music' }), null);
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'podcast' }), null);
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'video' }), null);
  assert.equal(collectionAddressFor({ source: 's', media_id: '1', media_type: 'tv' }), null);
  assert.equal(collectionAddressFor({ media_id: '1', media_type: 'movie' }), null);
  assert.equal(collectionAddressFor(null), null);
});

test('entryPayload maps the full form for POST', () => {
  const values = {
    format: 'Blu-ray', resolution: '1080p', hdr: 'HDR10', is3d: true,
    audioCodec: 'DTS', audioChannels: '5.1', bitrate: '320',
    purchasePrice: '9.99', purchaseLocation: 'Steam', collectedAt: '2026-01-02',
  };
  assert.deepEqual(entryPayload(values), {
    media_type: 'Blu-ray',
    resolution: '1080p',
    hdr: 'HDR10',
    is_3d: true,
    audio_codec: 'DTS',
    audio_channels: '5.1',
    bitrate: 320,
    purchase_price: '9.99',
    purchase_location: 'Steam',
    collected_at: '2026-01-02',
  });
});

test('entryPayload clears emptied fields for POST', () => {
  const values = {
    format: '', resolution: '', hdr: '', is3d: false,
    audioCodec: '', audioChannels: '', bitrate: '',
    purchasePrice: '', purchaseLocation: '', collectedAt: '',
  };
  assert.deepEqual(entryPayload(values), {
    media_type: '',
    resolution: '',
    hdr: '',
    is_3d: false,
    audio_codec: '',
    audio_channels: '',
    bitrate: null,
    purchase_price: null,
    purchase_location: '',
    collected_at: '',
  });
});

test('entryPayload with an initial snapshot sends only changes', () => {
  const initial = copyValuesFromCopy({
    mediaType: 'Blu-ray', resolution: '1080p', hdr: '', is3d: false,
    audioCodec: '', audioChannels: '', bitrate: '320',
    purchasePrice: '', purchaseLocation: '', collectedAt: '2026-01-02',
  });
  const values = { ...initial, hdr: 'HDR10', bitrate: '', purchasePrice: '12.50' };
  assert.deepEqual(entryPayload(values, initial), {
    hdr: 'HDR10',
    bitrate: null,
    purchase_price: '12.50',
  });
});

test('addressedEntryPayload keeps the supported subset and datetimes', () => {
  const values = {
    format: 'DVD', resolution: '480p', hdr: '', is3d: false,
    audioCodec: '', audioChannels: '', bitrate: '192',
    purchasePrice: '5.00', purchaseLocation: 'NAS', collectedAt: '2026-03-04',
  };
  assert.deepEqual(addressedEntryPayload(values), {
    media_type: 'DVD',
    resolution: '480p',
    is_3d: false,
    bitrate: 192,
    collected_at: '2026-03-04T00:00:00',
  });
});

test('copyFieldsFor mirrors the server per-type catalogs', () => {
  const games = copyFieldsFor('game');
  assert.deepEqual(games.map(field => field.name), ['resolution', 'format', 'hdr', 'purchasePrice', 'purchaseLocation', 'collectedAt']);
  assert.equal(games[0].label, 'Platform');
  assert.equal(games[2].label, 'Edition');
  assert.ok(games[0].options[0].value === '');

  assert.equal(copyFieldsFor('manga'), copyFieldsFor('book'));
  assert.equal(copyFieldsFor('comic_issue'), copyFieldsFor('book'));
  assert.equal(copyFieldsFor('podcast'), copyFieldsFor('movie'));
  assert.equal(copyFieldsFor('music').length, 7);
  assert.equal(copyFieldsFor('boardgame').length, 4);
});

test('emptyCopyValues resets every field', () => {
  const values = emptyCopyValues(copyFieldsFor('movie'));
  assert.equal(values.format, '');
  assert.equal(values.is3d, false);
  assert.equal(values.purchasePrice, '');
  assert.equal(Object.keys(values).length, copyFieldsFor('movie').length);
});

test('copyValuesFromCopy reads the serialized copy model', () => {
  assert.deepEqual(
    copyValuesFromCopy({
      mediaType: 'DVD', resolution: '480p', hdr: '', is3d: true,
      audioCodec: 'AAC', audioChannels: 'Stereo', bitrate: null,
      purchasePrice: '', purchaseLocation: '', collectedAt: '2026-01-02',
    }),
    {
      format: 'DVD', resolution: '480p', hdr: '', is3d: true,
      audioCodec: 'AAC', audioChannels: 'Stereo', bitrate: '',
      purchasePrice: '', purchaseLocation: '', collectedAt: '2026-01-02',
    },
  );
});

test('totalFromPayload and hasMoreFromPayload read the pagination block', () => {
  assert.equal(totalFromPayload({ pagination: { total: 250 } }), 250);
  assert.equal(totalFromPayload({}), null);
  assert.equal(hasMoreFromPayload({ pagination: { next: '/api/v1/collection/?limit=100&offset=100' } }), true);
  assert.equal(hasMoreFromPayload({ pagination: { next: null } }), false);
});

test('remote actions address the documented endpoints', async () => {
  const calls = [];
  const request = async (path, options) => {
    calls.push({ path, options });
    return { ok: true };
  };
  const actions = createRemoteCollectionActions(request);

  await actions.load({ limit: 100, offset: 100 });
  await actions.updateCopy({ entryId: 7, values: { hdr: 'HDR10', format: 'Blu-ray' }, initial: { hdr: '', format: 'Blu-ray' } });
  await actions.removeCopy({ entryId: 7 });
  await actions.updateSeason({ seasonId: 9, values: { hdr: 'HDR10' }, initial: { hdr: '' } });
  await actions.removeSeason({ seasonId: 9 });
  await actions.addCopy({
    address: { path: '/api/v1/media/movie/tmdb/1/collection/', query: undefined },
    values: { format: 'Blu-ray' },
  });

  assert.deepEqual(calls, [
    { path: '/api/v1/collection/', options: { query: { limit: 100, offset: 100 } } },
    { path: '/api/v1/collection/7/', options: { method: 'PATCH', body: { hdr: 'HDR10' } } },
    { path: '/api/v1/collection/7/', options: { method: 'DELETE' } },
    { path: '/api/v1/collection/seasons/9/', options: { method: 'PATCH', body: { hdr: 'HDR10' } } },
    { path: '/api/v1/collection/seasons/9/', options: { method: 'DELETE' } },
    {
      path: '/api/v1/media/movie/tmdb/1/collection/',
      options: { method: 'PUT', query: undefined, body: { media_type: 'Blu-ray' } },
    },
  ]);
});

test('updateCopy sends changed custom values and loadFields hits the fields route', async () => {
  const calls = [];
  const actions = createRemoteCollectionActions(async (path, options) => {
    calls.push({ path, options });
    return {};
  });
  await actions.loadFields();
  await actions.updateCopy({
    entryId: 2,
    values: { format: 'DVD' },
    initial: { format: 'DVD' },
    customValues: { 4: 'Good' },
    initialCustomValues: { 4: 'Mint' },
  });
  assert.deepEqual(calls, [
    { path: '/api/v1/collection/fields/', options: undefined },
    { path: '/api/v1/collection/2/', options: { method: 'PATCH', body: { custom_field_values: { 4: 'Good' } } } },
  ]);
});

test('updateCopy skips the request when nothing changed', async () => {
  let called = 0;
  const actions = createRemoteCollectionActions(async () => {
    called += 1;
    return {};
  });
  const values = { format: 'Blu-ray', hdr: '' };
  const outcome = await actions.updateCopy({ entryId: 3, values, initial: { ...values } });
  assert.deepEqual(outcome, { unchanged: true });
  assert.equal(called, 0);
});

test('addCopy rejects without an address instead of pretending to save', async () => {
  const actions = createRemoteCollectionActions(async () => {
    throw new Error('must not be called');
  });
  await assert.rejects(
    () => actions.addCopy({ address: null, values: {} }),
    error => error.message === ADD_COPY_UNAVAILABLE,
  );
});

test('local actions sign the load and refuse writes', async () => {
  const actions = createLocalCollectionActions('Sign in to your Floppy server to load your collection.');
  assert.deepEqual(await actions.load(), { local: true, reason: 'Sign in to your Floppy server to load your collection.' });
  await assert.rejects(() => actions.addCopy({ address: null, values: {} }));
  await assert.rejects(() => actions.updateCopy({ entryId: 1, values: {} }));
  await assert.rejects(() => actions.removeCopy({ entryId: 1 }));
});

test('the field manager round-trips the schema, keeping empty groups', async () => {
  const { managerGroupsFromPayload, fieldSchemaBody } = await import('./collectionTransportCore.js');
  const groups = managerGroupsFromPayload({
    groups: [
      { id: 3, name: 'Shelf', fields: [{ id: 9, label: 'Shelf slot', field_type: 'select', options: ['A', 'B'], media_types: ['movie'] }] },
      { id: 4, name: 'Empty', fields: [] },
    ],
  });
  assert.equal(groups.length, 2);
  assert.equal(groups[0].fields[0].optionsText, 'A\nB');
  groups[0].fields[0].optionsText = 'A\n B \n';
  const body = fieldSchemaBody(groups);
  assert.deepEqual(body.groups[0].fields[0].options, ['A', 'B']);
  assert.equal(body.groups[1].id, 4);
  assert.equal(fieldSchemaBody([{ name: ' New ', fields: [{ label: 'x', fieldType: 'text', mediaTypes: ['book'], optionsText: 'z' }] }])
    .groups[0].fields[0].options.length, 0);
});
