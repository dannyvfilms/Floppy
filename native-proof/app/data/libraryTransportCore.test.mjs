import assert from 'node:assert/strict';
import test from 'node:test';
import {
  cardModelFromRow,
  cardModelsFromRows,
  createLocalLibraryActions,
  createRemoteLibraryActions,
  defaultLibraryFilters,
  defaultSortDirection,
  libraryFilterOptions,
  libraryFilterSections,
  libraryMediaTypeOptions,
  libraryMediaTypeTitle,
  entrySourceLabel,
  libraryPastVerb,
  libraryQuery,
  librarySortOptions,
  libraryStatusOptions,
  listOptionsFromPayload,
  mediaRowFromPayload,
  summarizeBulkOutcome,
  tagOptionsFromPayload,
} from './libraryTransportCore.js';

test('library filter options mirror the server vocabulary', () => {
  const statuses = libraryStatusOptions();
  assert.deepEqual(statuses.map(option => option.value), [
    'no_status', 'completed', 'in_progress', 'planning', 'paused', 'dropped',
  ]);

  const movieSorts = librarySortOptions('movie').map(option => option.value);
  assert.ok(movieSorts.includes('score'));
  assert.ok(movieSorts.includes('release_date'));
  assert.ok(!movieSorts.includes('time_left'), 'time_left is TV only');
  assert.ok(!movieSorts.includes('time_to_beat'), 'time_to_beat is game only');
  assert.ok(movieSorts.includes('plays'), 'movies support plays sort');
  assert.ok(movieSorts.includes('critic_rating'));

  const tvSorts = librarySortOptions('tv').map(option => option.value);
  assert.ok(tvSorts.includes('time_left'));
  assert.ok(tvSorts.includes('next_episode_air_date'));

  const gameSorts = librarySortOptions('game');
  const endLabel = gameSorts.find(option => option.value === 'end_date');
  assert.equal(endLabel.label, 'Last Played');
  assert.ok(!gameSorts.map(option => option.value).includes('next_episode_air_date'));

  const bookEndLabel = librarySortOptions('book').find(option => option.value === 'end_date');
  assert.equal(bookEndLabel.label, 'Last Read');
  assert.ok(!librarySortOptions('book').map(option => option.value).includes('runtime'));

  assert.equal(defaultSortDirection('title'), 'asc');
  assert.equal(defaultSortDirection('score'), 'desc');

  const options = libraryFilterOptions({ mediaType: 'tv' });
  assert.equal(options.mediaTypes, undefined, 'per-type pages show no type picker');
  assert.equal(options.views.length, 2);
  const root = libraryFilterOptions({ mediaType: '', includeMediaTypes: true });
  assert.ok(root.mediaTypes.length >= 14);
  assert.equal(libraryMediaTypeTitle('season'), 'TV Seasons');
  assert.equal(libraryMediaTypeTitle('tv'), 'TV Shows');
  assert.equal(libraryPastVerb('game'), 'played');
  assert.equal(libraryPastVerb('movie'), 'watched');
  assert.equal(libraryMediaTypeTitle(undefined), 'Library');
  assert.ok(libraryMediaTypeOptions().some(option => option.value === 'comicissue'));
});

test('libraryQuery maps filter state onto the strict API contract', () => {
  const base = defaultLibraryFilters();
  assert.deepEqual(libraryQuery({ mediaType: 'tv', limit: 30, offset: 0, filters: base }), {
    limit: 30,
    offset: 0,
    sort: 'score',
    direction: 'desc',
  });

  const filters = defaultLibraryFilters();
  filters.statuses = ['in_progress', 'completed', 'no_status'];
  filters.sort = 'score';
  filters.direction = 'desc';
  filters.ranges.rating = { from: '7', to: '', within: '', unit: 'days' };
  filters.ranges.dateAdded = { from: '', to: '', within: '7', unit: 'days' };
  filters.fields.tags = ['3', '9'];
  filters.modes.tags = 'and';
  assert.deepEqual(libraryQuery({ mediaType: 'tv', filters }), {
    limit: 30,
    offset: 0,
    status: 'in_progress,completed,no_status',
    sort: 'score',
    direction: 'desc',
    rating_min: '7',
    date_added_within: '7',
    date_added_within_unit: 'days',
    tag: '3,9',
    tag_mode: 'and',
  });

  const ranged = defaultLibraryFilters();
  ranged.ranges.release = { from: '2024-01-01', to: '2024-12-31', within: '', unit: 'days' };
  ranged.ranges.completed = { from: '2026-01-01', to: '', within: '', unit: 'days' };
  const query = libraryQuery({ filters: ranged });
  assert.equal(query.release_date_from, '2024-01-01');
  assert.equal(query.release_date_to, '2024-12-31');
  assert.equal(query.completed_date_from, '2026-01-01');
  assert.equal(query.tag, undefined);

  const messy = defaultLibraryFilters();
  messy.ranges.rating = { from: 'high', to: '', within: '', unit: 'days' };
  messy.ranges.dateAdded = { from: 'tomorrow', to: '', within: 'x', unit: 'days' };
  const clean = libraryQuery({ filters: messy });
  assert.equal(clean.rating_min, undefined, 'malformed bounds are dropped, not sent');
  assert.equal(clean.date_added_from, undefined);
  assert.equal(clean.date_added_within, undefined);

  const typed = defaultLibraryFilters();
  typed.mediaTypes = ['game'];
  assert.equal(libraryQuery({ filters: typed }).media_type, 'game');
  const mixed = defaultLibraryFilters();
  mixed.mediaTypes = ['game', 'movie'];
  assert.equal(libraryQuery({ filters: mixed }).media_type, undefined,
    'multi-type selection has no API mapping and sends nothing');
  assert.equal(libraryQuery({ mediaType: 'tv', filters: typed }).media_type, undefined,
    'per-type pages do not send media_type');

  assert.deepEqual(libraryQuery({ mediaType: 'tv', search: 'dune', status: '3', limit: 5 }), {
    limit: 5,
    offset: 0,
    search: 'dune',
    status: '3',
  });
});

test('table Tags and Source cells read the API row like the web', () => {
  const base = { id: 1, status: 1, item: { media_type: 'movie', source: 'tmdb', media_id: '1', title: 'A' } };
  const filled = mediaRowFromPayload({ ...base, tags: ['Favorites', 'Cozy'], source: 'lastfm' });
  assert.equal(filled.cells.tags.text, 'Favorites, Cozy');
  assert.equal(filled.cells.source.text, 'Last.fm');
  const empty = mediaRowFromPayload({ ...base, source: '' });
  assert.equal(empty.cells.tags.text, '-');
  assert.equal(empty.cells.source.text, '--');
  assert.equal(entrySourceLabel('plex_server'), 'Plex server');
  assert.equal(entrySourceLabel('Theatre'), 'Theatre');
});

test('row payload maps into table rows and card models', () => {
  const row = mediaRowFromPayload({
    id: 10,
    item_id: 'tv/tmdb/1',
    status: 1,
    score: 8.5,
    progress: 6,
    episodes_left: 4,
    progress_unit: 'episodes',
    created_at: '2025-01-30T00:00:00Z',
    item: {
      media_type: 'tv',
      library_media_type: 'tv',
      source: 'tmdb',
      media_id: '1',
      title: 'The Quiet Orbit',
      image: 'https://example.com/show.jpg',
      release_datetime: '2024-01-01T00:00:00Z',
    },
  });
  const card = cardModelFromRow(row);
  assert.equal(card.title, 'The Quiet Orbit');
  assert.equal(card.identity.mediaId, '1');
  assert.equal(card.statusChip, null, 'the web library grid shows no status badge');
  assert.equal(card.lines.length, 0, 'the default sort prints no value line');
  const byProgress = cardModelFromRow(row, { sort: 'progress' });
  assert.equal(byProgress.lines[0].parts.length, 1, 'year and progress are never concatenated');
  assert.equal(byProgress.lines[0].parts[0].text, '6 / 10 episodes');
  const byRelease = cardModelFromRow(row, { sort: 'release_date' });
  assert.match(byRelease.lines[0].parts[0].text, /20\d\d/);
  assert.doesNotMatch(byRelease.lines[0].parts[0].text, /episodes/);
  assert.equal(card.rating.value, 8.5);
  assert.equal(card.actions.items[0].modal, 'track');
  assert.equal(card.actions.items[0].media.mediaId, '1');
  assert.equal(card.actions.items[1].modal, 'lists');
  assert.equal(card.actions.items[2].href, '/history');

  const untracked = cardModelFromRow(mediaRowFromPayload({
    id: 11,
    item_id: 'movie/tmdb/2',
    status: null,
    score: null,
    item: {
      media_type: 'movie',
      library_media_type: 'movie',
      source: 'tmdb',
      media_id: '2',
      title: 'Untracked Film',
      image: null,
    },
  }));
  assert.equal(untracked.statusChip, null);
  assert.equal(untracked.rating, null);
  assert.equal(untracked.lines.length, 0);

  const models = cardModelsFromRows([row, untracked]);
  assert.equal(models.length, 2);
  assert.equal(models[0].key, '10', 'cards are keyed by the numeric item id that bulk actions use');
  assert.equal(models[0].model.title, 'The Quiet Orbit');
});

test('tag and list options come from real payloads', () => {
  const tags = tagOptionsFromPayload({
    results: [
      { id: 1, name: 'Favorite', item_count: 4 },
      { id: 2, name: 'Sci-fi', item_count: 0 },
      { id: '', name: 'Broken' },
    ],
  });
  assert.deepEqual(tags, [
    { id: '1', name: 'Favorite', count: 4 },
    { id: '2', name: 'Sci-fi', count: 0 },
  ]);

  const lists = listOptionsFromPayload({
    results: [
      { id: 9, name: 'Weekend queue' },
      { name: 'No id' },
    ],
  });
  assert.deepEqual(lists, [{ id: '9', name: 'Weekend queue' }]);
});

test('bulk actions post one request to the library bulk endpoints', async () => {
  const calls = [];
  const request = async (path, options = {}) => {
    calls.push({ path, options });
    if (path.includes('/item-ids/')) return { item_ids: [3, 1, 3, 'x', -2] };
    return { success: true, message: 'Updated 2 item(s).' };
  };
  const transport = createRemoteLibraryActions(request);

  const status = await transport.bulkStatus(['7', 8, 8], 'Completed');
  assert.equal(status.message, 'Updated 2 item(s).');
  assert.equal(calls[0].path, '/api/v1/library/bulk/status/');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(calls[0].options.body, { item_ids: [7, 8], status: 'Completed' });

  await transport.bulkStatus([7], 'no_status');
  assert.equal(calls.at(-1).options.body.status, 'no_status');

  await transport.bulkAddToList([7], '5');
  assert.deepEqual(calls.at(-1).options.body, { item_ids: [7], list_id: 5 });
  assert.equal(calls.at(-1).path, '/api/v1/library/bulk/list/');

  await transport.bulkApplyTag([7], '4', 'remove');
  assert.deepEqual(calls.at(-1).options.body, { item_ids: [7], tag_id: 4, action: 'remove' });
  await transport.bulkApplyTag([7], '4');
  assert.equal(calls.at(-1).options.body.action, 'add');

  await transport.bulkAddToCollection([7]);
  assert.equal(calls.at(-1).path, '/api/v1/library/bulk/collection/');

  await transport.bulkAddPlays([7], { dry_run: true });
  assert.deepEqual(calls.at(-1).options.body, { item_ids: [7], dry_run: true });
  await transport.bulkPlaysStatus('ab12');
  assert.equal(calls.at(-1).path, '/api/v1/library/bulk/plays/ab12/');

  const ids = await transport.loadItemIds({ mediaType: 'movie', filters: defaultLibraryFilters() });
  assert.deepEqual(ids, [3, 1], 'ids are de-duplicated and validated');
  assert.equal(calls.at(-1).path, '/api/v1/media/movie/item-ids/');
  assert.equal(calls.at(-1).options.query.limit, undefined);

  const filters = defaultLibraryFilters();
  filters.statuses = ['completed'];
  filters.fields.genre = 'Drama';
  await transport.loadFilterOptions({ mediaType: 'movie', filters });
  const options = calls.at(-1);
  assert.equal(options.path, '/api/v1/media/movie/filter-options/');
  assert.equal(options.options.query.genre, 'Drama');
  assert.equal(options.options.query.status, 'completed');
  assert.equal(options.options.query.sort, undefined);

  const failing = createRemoteLibraryActions(async () => {
    throw new Error('Request failed (403).');
  });
  await assert.rejects(() => failing.bulkStatus([7], 'Completed'), /403/);
});

test('filter sections follow the web menu and the options endpoint', () => {
  const data = {
    genres: ['Crime', 'Drama'],
    implied_genres: [],
    years: [{ value: '2024', label: '2024' }, { value: 'unknown', label: 'Unknown' }],
    sources: [{ value: 'tmdb', label: 'TMDB' }],
    media_statuses: [],
    languages: [{ value: 'en', label: 'EN' }],
    countries: [],
    platforms: [{ value: 'PC', label: 'PC' }],
    formats: [],
    authors: [{ value: 'Ann', label: 'Ann' }],
    providers: [],
    tags: [{ id: 4, name: 'Favourites', count: 2 }],
    show_progress: true,
    show_languages: true,
    show_countries: false,
    show_platforms: true,
    show_formats: false,
    show_authors: true,
    author_is_channel: true,
    show_providers: false,
  };
  const keys = libraryFilterSections('game', data).map(section => section.key);
  assert.deepEqual(keys, [
    'rating', 'collection', 'progress', 'genre', 'year', 'release', 'source',
    'language', 'platform', 'author', 'tags',
  ]);
  const sections = libraryFilterSections('movie', { ...data, show_progress: false });
  assert.equal(sections.some(section => section.key === 'progress'), false);
  assert.equal(sections.find(section => section.key === 'author').label, 'Channel');
  assert.equal(sections.find(section => section.key === 'platform').type, 'multi');
  assert.equal(sections.find(section => section.key === 'tags').options[0].value, 'Favourites');
  assert.deepEqual(libraryFilterSections('movie', null).map(section => section.key),
    ['rating', 'collection', 'release']);

  const filters = defaultLibraryFilters();
  filters.fields.rating = 'rated';
  filters.fields.collection = 'all';
  filters.fields.genre = 'Drama';
  filters.fields.provider = '';
  filters.fields.platform = ['PC', 'Switch'];
  filters.modes.platform = 'not';
  filters.fields.tags = ['Favourites'];
  const query = libraryQuery({ mediaType: 'game', filters });
  assert.equal(query.rating, 'rated');
  assert.equal(query.collection, undefined, 'the neutral choice sends nothing');
  assert.equal(query.genre, 'Drama');
  assert.equal(query.provider, undefined);
  assert.equal(query.platform, 'PC,Switch');
  assert.equal(query.platform_mode, 'not');
  assert.equal(query.tag, 'Favourites');
  assert.equal(query.tag_mode, undefined);
});

test('bulk outcome summary reports honest counts', () => {
  assert.equal(summarizeBulkOutcome({ done: 3 }), '3 updated.');
  assert.equal(
    summarizeBulkOutcome({ done: 2, skipped: 1, failed: 1, firstError: 'Not found.' }),
    '2 updated, 1 skipped, 1 failed. Not found.',
  );
  assert.equal(summarizeBulkOutcome({}), 'Nothing changed.');
  assert.equal(summarizeBulkOutcome({ success: true, message: 'Updated 2 item(s).' }), 'Updated 2 item(s).');
});

test('local library actions keep every bulk action local', async () => {
  const transport = createLocalLibraryActions('Sign in to your Floppy server.');
  assert.equal(transport.mode, 'local');
  assert.equal((await transport.bulkStatus([], 'Completed')).local, true);
  assert.deepEqual(await transport.loadItemIds(), []);
  assert.equal((await transport.loadTags()).local, true);
  assert.equal((await transport.loadLists()).local, true);
});
