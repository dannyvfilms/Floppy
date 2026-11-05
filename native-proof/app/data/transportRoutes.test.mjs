import assert from 'node:assert/strict';
import test from 'node:test';
import { createCalendarTransport } from './calendarTransport.js';
import {
  createStatisticsTransport,
  flattenStatisticsModel,
} from './statisticsTransport.js';
import { createHistoryTransport, historyEntriesFromPayload } from './historyTransport.js';
import { createHomeTransport, mergeHomeRowPage } from './homeTransport.js';
import { createListTransport } from './listTransport.js';
import { createMusicTransport } from './musicTransport.js';
import {
  configureMediaCardTransport,
  hasMediaCardTransport,
  loadLists,
  resetMediaCardTransport,
} from '../surfaces/mediaCardTransport.js';

function authFixture(handler) {
  const calls = [];
  return {
    calls,
    session: {
      serverUrl: 'https://floppy.example',
      authType: 'token',
      request: async (path, options = {}) => {
        calls.push({ path, options });
        return handler ? handler(path, options) : null;
      },
    },
  };
}

test('list transport uses the authenticated request facade', async () => {
  const { calls, session } = authFixture();
  const transport = createListTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.updateVisibility({ listId: 7, visibility: 'private' });
  assert.equal(calls[0].path, '/api/v1/lists/7/');
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(calls[0].options.json, { visibility: 'private' });
});

test('list transport falls back to local preview without a session', () => {
  const transport = createListTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
});

test('calendar transport queues a server refresh through the session', async () => {
  const { calls, session } = authFixture();
  const transport = createCalendarTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.fetchReleases();
  assert.equal(calls[0].path, '/api/v1/calendar/update/');
  assert.equal(calls[0].options.method, 'POST');

  await transport.read();
  assert.equal(calls[1].path, '/api/v1/calendar/');
});

test('calendar transport keeps its local state without a session', async () => {
  const transport = createCalendarTransport();
  assert.equal(transport.mode, 'local');
  assert.equal((await transport.fetchReleases()).local, true);
});

test('media-card transport routes reads and writes through the session', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/lists/') return { results: [{ id: 1, name: 'Favorites' }] };
    if (path === '/api/v1/media/movie/tmdb/42/lists/') return { results: [{ list_id: 1 }] };
    return null;
  });
  configureMediaCardTransport({ auth: session });
  try {
    assert.equal(hasMediaCardTransport(), true);
    const model = await loadLists({ mediaType: 'movie', source: 'tmdb', mediaId: '42', title: 'Dune' }, 'Dune');
    assert.equal(model.lists.length, 1);
    assert.equal(model.lists[0].hasItem, true);
    assert.equal(calls[0].path, '/api/v1/lists/');
    assert.equal(calls[0].options.query.limit, 200);
    assert.equal(calls[1].path, '/api/v1/media/movie/tmdb/42/lists/');
  } finally {
    resetMediaCardTransport();
  }
  assert.equal(hasMediaCardTransport(), false);
});


test('music transport uses the authenticated request facade', async () => {
  const { calls, session } = authFixture();
  const transport = createMusicTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadArtistRelations({ artistId: 9 });
  assert.equal(calls[0].path, '/api/v1/music/artists/9/relations/');

  await transport.syncArtistMembers({ artistId: 9 });
  assert.equal(calls[1].path, '/api/v1/music/artists/9/sync-members/');
  assert.equal(calls[1].options.method, 'POST');

  await transport.syncAlbumMetadata({ albumId: 4 });
  assert.equal(calls[2].path, '/api/v1/music/albums/4/sync-metadata/');
  assert.equal(calls[2].options.method, 'POST');

  await transport.saveTrackNotes({ trackId: 12, notes: 'Side B' });
  assert.equal(calls[3].path, '/api/v1/music/tracks/12/notes/');
  assert.equal(calls[3].options.method, 'PATCH');
  assert.deepEqual(calls[3].options.json, { notes: 'Side B' });

  await transport.saveEpisodeNotes({ episodeId: 33, notes: 'Replay' });
  assert.equal(calls[4].path, '/api/v1/podcasts/episodes/33/notes/');
  assert.equal(calls[4].options.method, 'PATCH');

  await transport.deleteHistory({ mediaType: 'music', historyId: 88 });
  assert.equal(calls[5].path, '/api/v1/history/music/88/');
  assert.equal(calls[5].options.method, 'DELETE');
});

test('music transport keeps its local preview without a session', () => {
  const transport = createMusicTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
});

test('people transport reads person and studio profiles through the session', async () => {
  const { calls, session } = authFixture((path) => (
    path.startsWith('/studio/')
      ? { kind: 'studio', studio: { name: 'Northlight Interactive' } }
      : { kind: 'person', person: { name: 'Nora Voss' } }
  ));
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadPerson({ source: 'tmdb', personId: 1001, slug: 'nora-voss' });
  assert.equal(calls[0].path, '/person/tmdb/1001/nora-voss?format=json');

  await transport.loadStudio({ source: 'igdb', studioId: 88, slug: 'northlight' });
  assert.equal(calls[1].path, '/studio/igdb/88/northlight?format=json');
});

test('people transport keeps the local preview without a session', async () => {
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport();
  assert.equal(transport.mode, 'local');
  assert.equal((await transport.loadPerson({})).local, true);
});

test('statistics transport reads and writes through the authenticated session', async () => {
  const { calls, session } = authFixture(path => {
    if (path.startsWith('/statistics?format=json')) return { model: { summary: {} } };
    if (path.startsWith('/statistics/fragments/talent')) return { talent: {} };
    return { success: true };
  });
  const transport = createStatisticsTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadModel({ startDate: '2026-01-01', endDate: '2026-01-31' });
  assert.match(calls[0].path, /^\/statistics\?format=json/);
  assert.match(calls[0].path, /start-date=2026-01-01/);

  await transport.loadTalent({ rangeName: 'This Year' });
  assert.match(calls[1].path, /^\/statistics\/fragments\/talent\?format=json/);

  await transport.saveCompareMode({ compareMode: 'last_year' });
  assert.equal(calls[2].path, '/statistics/compare-mode');
  assert.deepEqual(calls[2].options.form, { compare_mode: 'last_year' });

  await transport.saveMediaTypes({ mediaTypes: ['movie', 'game'] });
  assert.deepEqual(calls[3].options.form, { media_types: 'movie,game' });

  await transport.saveGenreSort({ sortBy: 'plays', rangeName: 'This Year' });
  assert.equal(calls[4].path, '/statistics/genre-sort');
});

test('statistics transport keeps the local preview without a session', async () => {
  const transport = createStatisticsTransport();
  assert.equal(transport.mode, 'local');
  assert.equal(await transport.loadModel(), null);
  assert.equal((await transport.saveCompareMode({ compareMode: 'none' })).local, true);
});

test('flattenStatisticsModel maps grouped server charts and selected types', () => {
  const model = {
    summary: {
      all: { total: 4 },
      types: { movie: { total: 2 } },
      highlights: { all: [{ title: 'All' }], types: { movie: [{ title: 'Movie' }] } },
      scaleMax: 10,
    },
    charts: {
      overview: { all: { rhythm: { matrix: [] } }, types: { movie: { rhythm: { matrix: [[1]] } } } },
      hours: { all: { hoursByMonth: { labels: ['Jan'] } }, types: {} },
    },
    sections: {
      comparison: { rows: [{ type: 'movie' }] },
      overviews: { movie: { typeValue: 'movie', panels: [] } },
    },
  };
  const flat = flattenStatisticsModel(model, ['movie']);
  assert.equal(flat.summary.total, 2);
  assert.equal(flat.highlights[0].title, 'Movie');
  assert.deepEqual(flat.charts.rhythm.matrix, [[1]]);
  assert.equal(flat.charts.hoursByMonth.labels[0], 'Jan');
  assert.equal(flat.comparison.rows[0].type, 'movie');
  assert.equal(flat.overviews[0].typeValue, 'movie');
});

test('history transport reads a bounded page through the session', async () => {
  const { calls, session } = authFixture();
  const transport = createHistoryTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.load({ mediaTypes: ['movie'], from: '2026-01-01', limit: 5, offset: 10 });
  assert.equal(calls[0].path, '/api/v1/history/');
  assert.equal(calls[0].options.query.media_type, 'movie');
  assert.equal(calls[0].options.query.start_date, '2026-01-01');
  assert.equal(calls[0].options.query.limit, 5);
  assert.equal(calls[0].options.query.offset, 10);

  await transport.deleteRecord({ mediaType: 'movie', historyId: 42 });
  assert.equal(calls[1].path, '/api/v1/history/movie/42/');
  assert.equal(calls[1].options.method, 'DELETE');
});

test('history transport falls back to local preview without a session', async () => {
  const transport = createHistoryTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
  assert.equal((await transport.load()).local, true);
});

test('history entries map bounded API days into feed rows', () => {
  const entries = historyEntriesFromPayload({
    results: [{
      date: '2026-11-04',
      entries: [{
        entry_key: 'movie-7',
        instance_id: 7,
        media_type: 'movie',
        title: 'Dune',
        display_title: 'Dune',
        played_at_local: '2026-11-04T21:42:00-06:00',
        runtime_display: '2h 46min',
        runtime_minutes: 166,
        score: 9,
        item: { media_id: '603', source: 'tmdb', title: 'Dune' },
      }],
    }],
  });

  assert.equal(entries.length, 1);
  assert.equal(entries[0].date, '2026-11-04');
  assert.equal(entries[0].time, '21:42');
  assert.equal(entries[0].mediaType, 'movie');
  assert.equal(entries[0].historyId, 7);
  assert.equal(entries[0].sessions.length, 1);
  assert.equal(entries[0].sessions[0].runtimeMinutes, 166);
});

test('home transport reads presentation shelves, deferred rows and artwork', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/home/') return { groups: [{ mediaType: 'tv', rows: [] }], deferredGroups: [] };
    if (path === '/api/v1/home/row/4/') return { row: { rowId: 4, items: [{ id: 'b' }], loadedCount: 15 } };
    if (path === '/api/v1/home/row/4/sort/') return { row: { rowId: 4, direction: 'asc' } };
    return { rows: [], pollRowIds: [] };
  });
  const transport = createHomeTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  const model = await transport.load({ limit: 14 });
  assert.equal(calls[0].path, '/api/v1/home/');
  assert.equal(calls[0].options.query.presentation, 1);
  assert.equal(calls[0].options.query.deferred, 1);
  assert.equal(calls[0].options.query.limit, 14);
  assert.equal(model.groups.length, 1);

  const row = await transport.loadRow({ rowId: 4, offset: 14, seed: 9 });
  assert.equal(calls[1].path, '/api/v1/home/row/4/');
  assert.equal(calls[1].options.query.offset, 14);
  assert.equal(calls[1].options.query.seed, 9);
  assert.equal(row.loadedCount, 15);

  const sorted = await transport.sortRow({ rowId: 4 });
  assert.equal(calls[2].path, '/api/v1/home/row/4/sort/');
  assert.equal(calls[2].options.method, 'POST');
  assert.equal(sorted.direction, 'asc');

  await transport.refreshCovers({ ids: [4], pending: 2 });
  assert.equal(calls[3].path, '/api/v1/home/artwork/');
  assert.equal(calls[3].options.query.ids, '4');
});

test('home transport keeps the local preview and merges row pages', () => {
  const transport = createHomeTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
  const merged = mergeHomeRowPage(
    { rowId: 1, items: [{ id: 'a' }], loadedCount: 1, total: 2, seed: 4 },
    { items: [{ id: 'b' }], loadedCount: 2 },
  );
  assert.deepEqual(merged.items.map(item => item.id), ['a', 'b']);
  assert.equal(merged.loadedCount, 2);
  assert.equal(merged.seed, 4);
});
