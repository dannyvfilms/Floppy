import assert from 'node:assert/strict';
import test from 'node:test';
import {
  cardActionsFor,
  cardModelFromRow,
  cardModelsFromRows,
  defaultLibraryFilters,
  defaultSortDirection,
  entrySourceLabel,
  libraryFilterSections,
  libraryMediaTypeOptions,
  libraryMediaTypeTitle,
  libraryPastVerb,
  libraryPath,
  libraryQuery,
  librarySortOptions,
  listOptionsFromPayload,
  mediaRowFromPayload,
  summarizeBulkOutcome,
  tagOptionsFromPayload,
} from './libraryTransportCore.js';

test('libraryPath addresses the whole library and a single type', () => {
  assert.equal(libraryPath('tv'), '/api/v1/media/tv/');
  assert.equal(libraryPath(''), '/api/v1/media/');
  assert.equal(libraryPath('a b'), '/api/v1/media/a%20b/');
});

test('separate entries retain distinct card keys and group drills keep server filters', () => {
  const rows = [1, 2].map(entry_id => mediaRowFromPayload({ id: 4, entry_id, item: { title: 'Repeated film' } }));
  assert.deepEqual(cardModelsFromRows(rows).map(card => card.key), ['4:1', '4:2']);
  const query = libraryQuery({ mediaType: 'game', filters: { separateEntries: true, fields: { group_by: 'series', group: 'id:42', genre: 'RPG' } } });
  assert.equal(query.separate_entries, '1');
  assert.equal(query.group_by, 'series');
  assert.equal(query.group, 'id:42');
  assert.equal(query.genre, 'RPG');
  const group = mediaRowFromPayload({ group: { group_key: 'id:42', name: 'Series', game_count: 2, score: 8.5 } });
  assert.equal(group.groupKey, 'id:42');
  assert.equal(cardModelsFromRows([group])[0].model.actions, null);
});

test('entrySourceLabel uses the source vocabulary and capitalizes unknown values', () => {
  assert.equal(entrySourceLabel('imdb'), 'IMDb');
  assert.equal(entrySourceLabel('lastfm'), 'Last.fm');
  assert.equal(entrySourceLabel('unknown_source'), 'Unknown source');
  assert.equal(entrySourceLabel('MixedCase'), 'MixedCase');
  assert.equal(entrySourceLabel(''), '');
  assert.equal(entrySourceLabel(undefined), '');
});

test('mediaRowFromPayload renders an empty row with placeholders', () => {
  const row = mediaRowFromPayload({});
  assert.equal(row.id, '');
  assert.equal(row.title, '');
  assert.equal(row.cells.media_type.text, '');
  // The web media table (frontend/ui/MediaTable.jsx) uses ASCII placeholders:
  // '-' for an empty status, '--' for an empty runtime. Not an em dash.
  assert.equal(row.cells.status.text, '-');
  assert.equal(row.cells.status.muted, true);
  assert.equal(row.cells.score.rated, false);
  assert.deepEqual(row.cells.progress, { kind: 'progress', text: '', maxText: '', note: 'Total' });
  assert.equal(row.cells.runtime.text, '--');
  assert.equal(row.sort.release_date, null);
  assert.deepEqual(row.cells.genres, { kind: 'genres', items: [] });
});

test('mediaRowFromPayload falls back to the numeric item id', () => {
  assert.equal(mediaRowFromPayload({ id: 0 }).id, '0');
  assert.equal(mediaRowFromPayload({ item_id: 12 }).id, '12');
});

test('mediaRowFromPayload formats every progress unit', () => {
  const row = (payload) => mediaRowFromPayload(payload);
  assert.deepEqual(row({ progress: 90, progress_unit: 'minutes' }).cells.progress, {
    kind: 'progress', text: '1h 30m', maxText: ' played', note: 'Total',
  });
  assert.deepEqual(row({ progress: 1, progress_unit: 'plays' }).cells.progress, {
    kind: 'progress', text: '1', maxText: ' play', note: 'Total',
  });
  assert.deepEqual(row({ progress: 3, progress_unit: 'plays' }).cells.progress, {
    kind: 'progress', text: '3', maxText: ' plays', note: 'Total',
  });
  assert.deepEqual(row({ progress: 50, progress_unit: 'percent' }).cells.progress, {
    kind: 'progress', text: '50%', maxText: '', note: 'Total',
  });
  assert.deepEqual(row({ progress: 4, progress_unit: 'pages' }).cells.progress, {
    kind: 'progress', text: '4', maxText: ' pages', note: 'Total',
  });
  assert.deepEqual(row({ progress: 4, episodes_left: 2 }).cells.progress, {
    kind: 'progress', text: '4', maxText: ' / 6 episodes', note: 'Total',
  });
  const tracked = row({ progress: 4, episodes_left: 2 });
  assert.equal(tracked.track.progressMax, 6);
  assert.equal(tracked.track.progressLabel, 'Progress');
  assert.equal(row({ progress: 90, progress_unit: 'minutes' }).track.progressLabel, 'Minutes played');
});

test('tag and list options drop entries without id or name', () => {
  assert.deepEqual(tagOptionsFromPayload(undefined), []);
  assert.deepEqual(tagOptionsFromPayload([
    { id: 1, name: 'a', item_count: '4' },
    { id: '', name: 'b' },
    { id: 3 },
    { id: 4, name: '  ' },
  ]), [{ id: '1', name: 'a', count: 4 }]);
  assert.deepEqual(listOptionsFromPayload(undefined), []);
  assert.deepEqual(listOptionsFromPayload([{ id: 1, name: 'L' }]), [{ id: '1', name: 'L' }]);
});

test('card actions expose the track and lists modals plus the history link', () => {
  const actions = cardActionsFor('T', { mediaType: 'movie', source: 'tmdb', mediaId: '5' });
  assert.equal(actions.items.length, 3);
  assert.deepEqual(actions.modals, { track: 'track', lists: 'lists' });
  assert.equal(actions.items[2].href, '/history');
  assert.equal(actions.media.mediaId, '5');
});

test('cardModelFromRow keeps the sort line and unrated cards unmarked', () => {
  const baseRow = mediaRowFromPayload({ id: 1, item: { media_type: 'movie', title: 'A', image: null } });
  const plain = cardModelFromRow(baseRow, {});
  assert.deepEqual(plain.lines, []);
  assert.equal(plain.rating, null);
  assert.equal(plain.video, false);
  const progressRow = mediaRowFromPayload({ id: 2, progress: 4, episodes_left: 2 });
  const sorted = cardModelFromRow(progressRow, { sort: 'progress' });
  assert.equal(sorted.lines[0].parts[0].text, '4 / 6 episodes');
  assert.deepEqual(cardModelsFromRows(undefined), []);
  const models = cardModelsFromRows([{ ...baseRow, id: 9 }], {});
  assert.equal(models[0].key, '9');
  assert.equal(models[0].row.id, 9);
});

test('summarizeBulkOutcome prefers the server message and reports failures', () => {
  assert.equal(summarizeBulkOutcome({ message: 'ok' }), 'ok');
  assert.equal(summarizeBulkOutcome({ done: 2, skipped: 1 }), '2 updated, 1 skipped.');
  assert.equal(summarizeBulkOutcome({ done: 2, failed: 1, firstError: 'boom' }), '2 updated, 1 failed. boom');
  assert.equal(summarizeBulkOutcome({}), 'Nothing changed.');
  assert.equal(summarizeBulkOutcome(undefined), 'Nothing changed.');
});

test('the shared vocabularies cover every media type', () => {
  assert.ok(libraryMediaTypeOptions().some(option => option.value === 'comicissue' && option.label === 'Comic Issues'));
  assert.equal(libraryMediaTypeOptions().length, 14);
  assert.equal(libraryPastVerb('manga'), 'read');
  assert.equal(libraryPastVerb('banana'), 'watched');
  assert.equal(libraryMediaTypeTitle(''), 'Library');
  assert.equal(libraryMediaTypeTitle('boardgame'), 'Board Games');
  assert.equal(defaultSortDirection('title'), 'asc');
  assert.equal(defaultSortDirection('date_added'), 'desc');
});

test('sort options follow the per-type guards and end-date relabels', () => {
  const valuesFor = mediaType => librarySortOptions(mediaType).map(option => option.value);
  const movie = valuesFor('movie');
  assert.ok(movie.includes('runtime') && movie.includes('critic_rating'));
  assert.ok(!movie.includes('progress'));
  assert.ok(!movie.includes('time_to_beat'));
  assert.ok(!movie.includes('author'));
  assert.ok(valuesFor('tv').includes('time_left'));
  const game = valuesFor('game');
  assert.ok(game.includes('time_to_beat') && game.includes('platform') && game.includes('progress'));
  assert.ok(!game.includes('runtime'));
  const book = librarySortOptions('book');
  assert.ok(book.some(option => option.value === 'author'));
  assert.ok(book.some(option => option.value === 'end_date' && option.label === 'Last Read'));
  assert.ok(librarySortOptions('game').some(option => option.value === 'end_date' && option.label === 'Last Played'));
});

test('libraryQuery sends only set parameters', () => {
  assert.deepEqual(libraryQuery({ mediaType: 'movie' }), { limit: 30, offset: 0 });
  assert.deepEqual(
    libraryQuery({ search: 'x', status: 'completed', sort: 'score', direction: 'desc', limit: 10, offset: 20 }),
    { limit: 10, offset: 20, search: 'x', status: 'completed', sort: 'score', direction: 'desc' },
  );
});

test('libraryQuery maps the filter state onto the media-list contract', () => {
  assert.deepEqual(
    libraryQuery({ filters: { mediaTypes: ['movie'] } }),
    { limit: 30, offset: 0, media_type: 'movie' },
  );
  assert.deepEqual(
    libraryQuery({ mediaType: 'tv', filters: { mediaTypes: ['movie'] } }),
    { limit: 30, offset: 0 },
  );
  const query = libraryQuery({
    filters: {
      statuses: ['completed', 'planning'],
      sort: 'title',
      direction: 'asc',
      ranges: {
        rating: { from: '7', to: '9.5' },
        dateAdded: { within: '3', unit: 'weeks' },
        release: { from: '2026-01-01' },
        completed: { within: '0', from: '2026-02-01' },
      },
      fields: { rating: 'all', tags: ['a', 'b'], genre: 'comedy' },
      modes: { tags: 'and' },
    },
  });
  assert.equal(query.status, 'completed,planning');
  assert.equal(query.sort, 'title');
  assert.equal(query.direction, 'asc');
  assert.equal(query.rating_min, '7');
  assert.equal(query.rating_max, '9.5');
  assert.equal(query.date_added_within, '3');
  assert.equal(query.date_added_within_unit, 'weeks');
  assert.equal(query.release_date_from, '2026-01-01');
  assert.equal(query.completed_date_from, '2026-02-01');
  assert.equal(query.completed_date_within, undefined);
  assert.equal(query.tag, 'a,b');
  assert.equal(query.tag_mode, 'and');
  assert.equal(query.genre, 'comedy');
  assert.equal(query.rating, undefined);
  const orTags = libraryQuery({ filters: { fields: { tags: ['a'] }, modes: { tags: 'or' } } });
  assert.equal(orTags.tag, 'a');
  assert.equal(orTags.tag_mode, undefined);
});

test('libraryFilterSections keeps the static sections and adds only the filled ones', () => {
  assert.deepEqual(libraryFilterSections('movie', {}).map(section => section.key), [
    'rating', 'collection', 'release',
  ]);
  const sections = libraryFilterSections('movie', {
    show_progress: true,
    genres: ['Action'],
    tags: [{ name: 'x', count: 2 }],
  });
  assert.deepEqual(sections.map(section => section.key), [
    'rating', 'collection', 'progress', 'genre', 'release', 'tags',
  ]);
  const genre = sections.find(section => section.key === 'genre');
  assert.deepEqual(genre.options, [{ value: 'Action', label: 'Action' }]);
  const tags = sections.find(section => section.key === 'tags');
  assert.deepEqual(tags.options, [{ value: 'x', label: 'x (2)' }]);
  assert.equal(tags.type, 'multi');
  const author = libraryFilterSections('book', {
    show_authors: true,
    authors: ['A'],
    author_is_channel: true,
  }).find(section => section.key === 'author');
  assert.equal(author.label, 'Channel');
});

test('defaultLibraryFilters start on the score grid with everything cleared', () => {
  const filters = defaultLibraryFilters();
  assert.equal(filters.sort, 'score');
  assert.equal(filters.direction, 'desc');
  assert.equal(filters.view, 'grid');
  assert.deepEqual(filters.fields.tags, []);
  assert.equal(filters.fields.rating, 'all');
});

test('initial rides the query and saved queries round trip into filter state', async () => {
  const core = await import('./libraryTransportCore.js');
  const filters = { ...core.defaultLibraryFilters(), initial: 'm', statuses: ['Completed', 'Paused'], fields: { ...core.defaultLibraryFilters().fields, tags: ['a', 'b'] } };
  const query = core.libraryQuery({ mediaType: 'movie', filters });
  assert.equal(query.initial, 'm');
  const restored = core.filtersFromSavedQuery('status=Completed&status=Paused&tag=a&tag=b&sort=title&direction=asc&layout=table&initial=m');
  assert.deepEqual(restored.statuses, ['Completed', 'Paused']);
  assert.deepEqual(restored.fields.tags, ['a', 'b']);
  assert.equal(restored.sort, 'title');
  assert.equal(restored.view, 'table');
  assert.equal(restored.initial, 'm');
  assert.deepEqual(core.filtersFromSavedQuery('status=all').statuses, []);
});

test('stored preferences replace the hardcoded score and grid defaults', async () => {
  const core = await import('./libraryTransportCore.js');
  const next = core.filtersFromPreferences({ layout: 'table', sort: 'title', direction: '' });
  assert.equal(next.view, 'table');
  assert.equal(next.sort, 'title');
  assert.equal(next.direction, 'asc');
  assert.equal(core.filtersFromPreferences(null).sort, 'score');
});

test('saved view, share and preference calls address the library endpoints', async () => {
  const core = await import('./libraryTransportCore.js');
  const calls = [];
  const actions = core.createRemoteLibraryActions(async (path, options) => { calls.push([path, options]); return { url: '/list/1' }; });
  await actions.createSavedView({ mediaType: 'movie', name: 'Best', filters: { ...core.defaultLibraryFilters(), view: 'table' } });
  assert.equal(calls[0][0], '/api/v1/library/saved-views/');
  assert.equal(calls[0][1].body.query.layout, 'table');
  assert.equal(calls[0][1].body.query.limit, undefined);
  assert.equal(await actions.shareView({ mediaType: 'movie', filters: core.defaultLibraryFilters() }), '/list/1');
  await actions.savePreferences('movie', { layout: 'grid' });
  assert.equal(calls[2][0], '/api/v1/library/preferences/movie/');
  assert.equal(calls[2][1].method, 'PATCH');
});
