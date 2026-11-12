import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeTrackForm, initialTrackValues } from '../../../frontend/ui/mediaCardForms.js';
import { createCalendarTransport } from './calendarTransport.js';
import {
  createStatisticsTransport,
  statisticsModelFromPayload,
} from './statisticsTransport.js';
import {
  createHistoryTransport,
  genreOptionsFromPayload,
  historyEntriesFromPayload,
  historyMonthNav,
  monthBounds,
  monthKey,
  shiftMonth,
  todayKey,
} from './historyTransport.js';
import { createHomeTransport, mergeHomeRowPage } from './homeTransport.js';
import { createListTransport, listItemsFromPayload } from './listTransport.js';
import { calendarModelFromPayload } from './calendarTransport.js';
import {
  createDiscoverTransport,
  discoverRowsFromPayload,
  hiddenFromPayload,
} from './discoverTransport.js';
import { createLibraryTransport, mediaRowsFromPayload } from './libraryTransport.js';
import {
  createSearchTransport,
  searchBarFromPayload,
  suggestionsFromPayload,
} from './searchTransport.js';
import {
  collectionItemsFromPayload,
  createCollectionTransport,
} from './collectionTransport.js';
import {
  createSettingsTransport,
  preferencesToForm,
} from './settingsTransport.js';
import { createMusicTransport } from './musicTransport.js';
import {
  configureMediaCardTransport,
  hasMediaCardTransport,
  loadLists,
  loadTrack,
  saveTrack,
  resetMediaCardTransport,
  unwatchEpisode,
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

test('an untracked comic issue submits its required zero progress and date fields', async () => {
  const { calls, session } = authFixture(path => path.endsWith('/state/')
    ? { tracked: false, consumptions: [] }
    : path === '/api/v1/media/comicissue/comicvine/760231/'
      ? { title: 'Batman #1', max_progress: 1 } : null);
  configureMediaCardTransport({ auth: session });
  try {
    const identity = { mediaType: 'comicissue', source: 'comicvine', mediaId: '760231' };
    const loaded = await loadTrack(identity);
    const model = normalizeTrackForm(loaded.model);
    assert.equal(loaded.model.fields.find(field => field.name === 'progress').value, '0');
    assert.ok(loaded.model.fields.some(field => field.name === 'start_date'));
    assert.ok(model.fields.some(field => field.name === 'entry_source'));
    assert.ok(model.fields.some(field => field.name === 'notes'));
    assert.ok(model.fields.find(field => field.name === 'status').options.some(option => option.label === 'No Status'));
    await saveTrack(identity, model, { ...initialTrackValues(model), status: '', entry_source: 'Import', notes: 'Review note' }, false);
    const created = calls.find(call => call.options.method === 'POST');
    assert.equal(created.path, '/api/v1/media/comicissue/');
    assert.equal(created.options.body.progress, 0);
    assert.equal(created.options.body.media_id, '760231');
    assert.equal(created.options.body.status, null);
    assert.equal(created.options.body.entry_source, 'Import');
    assert.equal(created.options.body.notes, 'Review note');
    await saveTrack(identity, model, { ...initialTrackValues(model), status: '', entry_source: '' }, true);
    const updated = calls.find(call => call.options.method === 'PATCH');
    assert.equal(updated.options.body.entry_source, '');
    assert.equal(updated.options.body.status, null);
  } finally { resetMediaCardTransport(); }
});

test('track datetime-local values round trip in the viewer timezone without shifting date-only values', async () => {
  const originalTimezone = process.env.TZ;
  const identity = { mediaType: 'episode', source: 'tmdb', mediaId: '31911', seasonNumber: 1, episodeNumber: 1 };
  try {
    for (const [timezone, local, expected] of [
      ['America/Chicago', '2026-11-10T04:00', '2026-11-10T10:00:00.000Z'],
      ['America/Chicago', '2026-07-10T04:00', '2026-07-10T09:00:00.000Z'],
      ['Asia/Tokyo', '2026-11-10T04:00', '2026-11-09T19:00:00.000Z'],
    ]) {
      process.env.TZ = timezone;
      let persisted;
      const { calls, session } = authFixture((path, options) => {
        if (options.method === 'POST') persisted = options.body.end_date;
        return { tracked: Boolean(persisted), consumptions: persisted ? [{ end_date: persisted }] : [] };
      });
      configureMediaCardTransport({ auth: session });
      const loaded = await loadTrack(identity, { trackTime: true });
      await saveTrack(identity, loaded.model, { end_date: local }, false);
      assert.equal(persisted, expected);
      const reopened = await loadTrack(identity, { trackTime: true });
      assert.equal(reopened.model.fields.find(field => field.name === 'end_date').value, local);
      await saveTrack(identity, reopened.model, { end_date: '2026-11-10' }, true);
      assert.equal(persisted, '2026-11-10');
      await saveTrack({ mediaType: 'movie', source: 'tmdb', mediaId: '603' }, {
        fields: [{ name: 'end_date', type: 'date' }],
      }, { end_date: local }, true);
      assert.equal(calls.find(call => call.options.method === 'PATCH').options.body.end_date, expected);
      resetMediaCardTransport();
    }
  } finally {
    if (originalTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = originalTimezone;
    resetMediaCardTransport();
  }
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
    path.startsWith('/api/v1/studios/')
      ? { kind: 'studio', studio: { name: 'Northlight Interactive' } }
      : { kind: 'person', person: { name: 'Nora Voss' } }
  ));
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadPerson({
    source: 'tmdb', personId: 1001, filters: { sort: 'title', direction: 'asc', rating: 'all', year: '' },
  });
  assert.equal(calls[0].path, '/api/v1/people/tmdb/1001/');
  assert.deepEqual(calls[0].options.query, { sort: 'title', direction: 'asc' });

  await transport.loadStudio({ source: 'igdb', studioId: 88 });
  assert.equal(calls[1].path, '/api/v1/studios/igdb/88/');
});

test('people transport reports signed out without a session', async () => {
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport();
  assert.equal(transport.mode, 'local');
  await assert.rejects(() => transport.loadPerson({}), /Sign in/);
});

test('statistics transport reads the scoped overview and writes through the session', async () => {
  const { calls, session } = authFixture(path => {
    if (path.startsWith('/api/v1/statistics/overview/')) {
      return { range: { range_name: 'Last 12 Months' }, statistics: {} };
    }
    return { scheduled: true };
  });
  const transport = createStatisticsTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadModel({ startDate: '2026-01-01', endDate: '2026-01-31' });
  assert.match(calls[0].path, /^\/api\/v1\/statistics\/overview\/\?/);
  assert.match(calls[0].path, /start_date=2026-01-01/);
  assert.match(calls[0].path, /end_date=2026-01-31/);

  await transport.loadModel({ startDate: 'all', endDate: 'all' });
  assert.match(calls[1].path, /start_date=all/);

  await transport.saveMediaTypes({ mediaTypes: ['movie', 'game'] });
  assert.equal(calls[2].path, '/api/v1/statistics/preferences/');
  assert.equal(calls[2].options.method, 'PATCH');
  assert.deepEqual(calls[2].options.body, { media_types: ['movie', 'game'] });

  await transport.saveTopTalentSort({ sortBy: 'time', rangeName: 'This Year' });
  assert.equal(calls[3].path, '/api/v1/statistics/preferences/');
  assert.deepEqual(calls[3].options.body, { top_talent_sort_by: 'time' });

  await transport.saveStudioSort({ sortBy: 'plays', rangeName: 'This Year' });
  assert.deepEqual(calls[4].options.body, { studio_sort_by: 'plays' });

  await transport.requestRefresh({ rangeName: 'Last 90 Days' });
  assert.equal(calls[5].path, '/api/v1/statistics/refresh/');
  assert.equal(calls[5].options.method, 'POST');
  assert.deepEqual(calls[5].options.form, { range_name: 'Last 90 Days' });
});

test('statistics transport keeps the local prompt without a session', async () => {
  const transport = createStatisticsTransport();
  assert.equal(transport.mode, 'local');
  assert.equal(await transport.loadModel(), null);
  assert.equal((await transport.requestRefresh({ rangeName: 'Last 90 Days' })).local, true);
});

test('statistics model maps the overview payload into shared statistics models', () => {
  const payload = {
    range: { start_date: '2026-01-01', end_date: '2026-01-31', range_name: 'This Month' },
    statistics: {
      media_count: { total: 3, movie: 2, tv: 1 },
      activity_data: {
        calendar_weeks: [[
          { date: '2026-01-05', count: 2, by_type: { movie: 2 }, future: false },
          { date: '2026-01-12', count: 0, future: true },
        ]],
        months: [['Jan', 2]],
        weekday_labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        stats: {},
      },
      media_type_distribution: { labels: ['Movie'], datasets: [{ data: [4], backgroundColor: ['#f97316'] }] },
      score_distribution: {
        labels: ['1', '2'],
        datasets: [{ label: 'Movie', data: [1, 2], background_color: '#f97316' }],
        scale_max: 10,
      },
      top_played: {
        movie: [{
          formatted_duration: '2h 46min',
          play_count: 4,
          media: { score: 9, item: { media_id: '603', source: 'tmdb', media_type: 'movie', title: 'Dune', image: 'https://example.com/dune.jpg' } },
        }],
      },
      top_rated_by_type: {
        movie: [{ score: 9, item: { media_id: '603', source: 'tmdb', media_type: 'movie', title: 'Dune' } }],
      },
      top_talent: {
        sort_by: 'plays',
        by_sort: {
          plays: {
            top_actors: [{ name: 'Nora Voss', source: 'tmdb', person_id: '1', plays: 12, watched_minutes: 200, watched_time: '3h 20m', unique_titles: 5 }],
            top_actresses: [], top_directors: [], top_writers: [],
            top_studios: [{ name: 'A24', source: 'tmdb', studio_id: '9', plays: 8, watched_minutes: 400, watched_time: '6h 40m' }],
          },
          time: { top_actors: [], top_actresses: [], top_directors: [], top_writers: [], top_studios: [] },
          titles: { top_actors: [], top_actresses: [], top_directors: [], top_writers: [], top_studios: [] },
        },
      },
      status_distribution: {
        labels: ['Movie'],
        datasets: [{ label: 'Completed', data: [2], background_color: '#10b981' }],
      },
      minutes_per_media_type: { movie: 300 },
      weekday_hour_chart_data: { all: [[0], [0], [0], [0], [0], [0], [0]], movie: [[1], [2], [0], [0], [0], [0], [0]] },
      combined_plays_charts: {
        by_month: { all: { labels: ['Jan'], datasets: [{ data: [5] }] } },
        by_weekday: {}, by_time_of_day: {},
      },
      summary_stats_by_type: {
        all: {
          completed: 2, total: 3, total_minutes: 900, average_score: 8.5, has_score: true,
          most_active_day: 'Monday', most_active_day_percentage: 40,
          current_streak: 2, longest_streak: 5,
          longest_streak_start: '2026-01-01', longest_streak_end: '2026-01-05',
        },
        movie: { completed: 2, total: 2, total_minutes: 300, average_score: null, has_score: false },
      },
      history_highlights: {
        first_play: { title: 'Dune', media_type: 'movie', image: 'https://example.com/dune.jpg', played_at: '2026-01-05T20:00:00Z', item: { media_id: '603', source: 'tmdb', media_type: 'movie', title: 'Dune' } },
        last_play: null,
        today_card: {},
      },
      history_highlights_by_type: {},
      movie_consumption: { has_data: true, charts: { by_year: { labels: ['2026'], datasets: [{ data: [4] }] } } },
      game_consumption: { has_data: false },
    },
  };

  const all = statisticsModelFromPayload(payload, []);
  assert.equal(all.summary.total, 3);
  assert.equal(all.summary.totalHours, 15);
  assert.equal(all.summary.typeLabel, 'titles');
  assert.deepEqual(all.summary.comparison, {});
  assert.equal(all.highlights[0].title, 'Dune');
  assert.equal(all.highlights[0].href, '/details/tmdb/movie/603');
  assert.equal(all.highlights[0].date, 'Played Jan 5, 2026');
  assert.deepEqual(all.charts.rhythm.matrix, [[0], [0], [0], [0], [0], [0], [0]]);
  assert.deepEqual(all.charts.mediaTypeHours.labels, ['Movie']);
  assert.deepEqual(all.charts.mediaTypeHours.data, [4]);
  assert.equal(all.charts.heatmap.weeks[0].days[0].level, 1);
  assert.equal(all.charts.heatmap.weeks[0].days[0].count, 2);
  assert.equal(all.charts.heatmap.weeks[0].days[1].future, true);
  assert.deepEqual(all.charts.hoursByMonth.labels, ['Jan']);
  assert.deepEqual(all.charts.hoursByWeekday.data, []);
  assert.deepEqual(all.charts.statusComposition.labels, ['Completed']);
  assert.deepEqual(all.charts.ratingDistribution.labels, ['1', '2']);
  assert.equal(all.charts.ratingDistribution.scaleMax, 10);
  assert.equal(all.charts.statusBreakdown.rows[0].label, 'Movie');
  assert.equal(all.charts.statusBreakdown.rows[0].total, 2);
  assert.equal(all.charts.completion.rows.length, 1);
  assert.equal(all.charts.completion.rows[0].completed, 2);
  assert.equal(all.talent.roleLeaders.columns[0].bucket, 'actors');
  assert.equal(all.talent.roleLeaders.columns[0].entries[0].displayMetric, '12');
  assert.equal(all.talent.studioFootprint.studios[0].pct, 100);
  assert.equal(all.talent.studioFootprint.studios[0].metricLabel, '8 plays');
  assert.deepEqual(all.talent.tasteSignals.sortOptions, []);
  assert.equal(all.overviews.length, 1);
  assert.equal(all.overviews[0].typeValue, 'movie');
  assert.equal(all.overviews[0].panels[0].title, 'Most Played');
  assert.equal(all.overviews[0].panels[0].items[0].subtitle, '2h 46min · 4 plays');
  assert.equal(all.overviews[0].panels[1].title, 'Top Rated');
  assert.deepEqual(all.mediaTypeOptions, [{ value: 'movie', label: 'Movie' }]);
  assert.equal(all.rangeName, 'This Month');

  const focused = statisticsModelFromPayload(payload, ['movie']);
  assert.equal(focused.summary.total, 2);
  assert.equal(focused.summary.typeLabel, 'films');
  assert.deepEqual(focused.charts.rhythm.matrix, [[1], [2], [0], [0], [0], [0], [0]]);
  assert.deepEqual(focused.charts.mediaTypeHours.data, [5]);
  assert.equal(focused.highlights.length, 1);
  assert.deepEqual(focused.comparison, {});
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

test('history month helpers anchor navigation on real dates', () => {
  const now = new Date(2026, 10, 9); // 2026-11-09 local time
  assert.deepEqual(monthKey(now), { year: 2026, month: 11 });
  assert.equal(todayKey(now), '2026-11-09');
  assert.deepEqual(monthBounds({ year: 2026, month: 11 }), { from: '2026-11-01', to: '2026-11-30' });
  assert.deepEqual(monthBounds({ year: 2024, month: 2 }), { from: '2024-02-01', to: '2024-02-29' });
  assert.deepEqual(shiftMonth({ year: 2026, month: 12 }, 1), { year: 2027, month: 1 });
  assert.deepEqual(shiftMonth({ year: 2026, month: 1 }, -1), { year: 2025, month: 12 });
  assert.deepEqual(shiftMonth({ year: 2026, month: 11 }, -12), { year: 2025, month: 11 });
});

test('history month nav mirrors the web header labels and blocking', () => {
  const now = new Date(2026, 10, 9);
  const nav = historyMonthNav({ year: 2026, month: 11 }, now);
  assert.equal(nav.monthLabel, 'November');
  assert.deepEqual(nav.previousYear, { label: '2025' });
  assert.equal(nav.previousMonth.label, 'Oct');
  assert.equal(nav.nextMonth.label, 'Dec');
  assert.equal(nav.nextMonth.disabled, true);
  assert.equal(nav.currentMonth.label, '2026');
  assert.equal(nav.currentMonth.disabled, true);

  const october = historyMonthNav({ year: 2026, month: 10 }, now);
  assert.equal(october.monthLabel, 'October');
  assert.equal(october.previousMonth.label, 'Sep');
  assert.equal(october.nextMonth.label, 'Nov');
  assert.equal(october.nextMonth.disabled, false);
  assert.equal(october.currentMonth.disabled, false);

  const january = historyMonthNav({ year: 2026, month: 1 }, now);
  assert.equal(january.previousMonth.label, 'Dec');
  assert.equal(january.previousYear.label, '2025');
});

test('history genre options map the session endpoint payload', () => {
  assert.deepEqual(genreOptionsFromPayload({
    genres: ['Science fiction', ' Drama ', ''],
    implied_genres: ['Space'],
  }), {
    genres: ['Science fiction', 'Drama'],
    impliedGenres: ['Space'],
  });
  assert.deepEqual(genreOptionsFromPayload(null), { genres: [], impliedGenres: [] });
});

test('history transport loads genre options through the session', async () => {
  const calls = [];
  const session = {
    request: async (path) => {
      calls.push(path);
      return { genres: ['Action'], implied_genres: ['Space'] };
    },
  };
  const transport = createHistoryTransport({ auth: session });
  const options = await transport.loadGenreOptions();
  assert.deepEqual(calls, ['/api/v1/history/genres/']);
  assert.deepEqual(options, { genres: ['Action'], impliedGenres: ['Space'] });
});

test('history genre options stay empty without a session', async () => {
  const transport = createHistoryTransport();
  assert.equal(transport.mode, 'local');
  assert.deepEqual(await transport.loadGenreOptions(), { genres: [], impliedGenres: [] });
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

test('calendar transport loads a month and maps releases', async () => {
  const { calls, session } = authFixture(() => ({
    pagination: { total: 1 },
    results: [{
      id: 9,
      datetime: '2026-11-07T01:00:00Z',
      release_type: '',
      content_number: 5,
      item: {
        media_type: 'episode',
        library_media_type: 'season',
        title: 'Sheriff Country',
        season_number: 2,
        episode_number: 5,
        image: 'https://example.com/poster.jpg',
        url: '/details/tvdb/tv/1/season/2',
        release_datetime: '2026-01-01T00:00:00Z',
      },
    }],
  }));
  const transport = createCalendarTransport({ auth: session });
  await transport.read({ month: 11, year: 2026 });
  assert.equal(calls[0].path, '/api/v1/calendar/');
  assert.deepEqual(calls[0].options.query, { month: 11, year: 2026 });

  const model = calendarModelFromPayload({
    results: [{
      id: 9,
      datetime: '2026-11-07T12:00:00Z',
      release_type: '',
      content_number: 5,
      item: {
        media_type: 'episode',
        library_media_type: 'season',
        title: 'Sheriff Country',
        season_number: 2,
        image: 'https://example.com/poster.jpg',
        release_datetime: '2026-01-01T00:00:00Z',
      },
    }],
  }, { month: 11, year: 2026, today: new Date(2026, 10, 4) });
  assert.equal(model.monthName, 'November');
  assert.equal(model.selectedDay, 4);
  assert.equal(model.releases['7'][0].mediaType, 'season');
  assert.equal(model.releases['7'][0].episodeLabel, 'S02E05');
  assert.equal(model.releases['7'][0].title, 'Sheriff Country');
});

test('calendar transport pages a full month through the offset envelope', async () => {
  const { calls, session } = authFixture((path, options) => {
    const offset = options.query.offset;
    if (offset === 0) {
      return { pagination: { total: 3, next: 'http://floppy.example/api/v1/calendar/?offset=2' }, results: [{ id: 1 }, { id: 2 }] };
    }
    return { pagination: { total: 3, next: null }, results: [{ id: 3 }] };
  });
  const transport = createCalendarTransport({ auth: session });
  const page = await transport.readAll({ month: 11, year: 2026 });
  assert.equal(calls[0].options.query.limit, 200);
  assert.equal(calls[1].options.query.offset, 2);
  assert.equal(page.results.length, 3);
  assert.equal(page.pagination.total, 3);
});

test('discover transport loads rows, hidden entries and queues refresh', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/discover/') return { rows: [{ key: 'top', title: 'Top', why: 'Why', items: [] }] };
    if (path === '/api/v1/discover/hidden/') return { results: [] };
    return { accepted: true };
  });
  const transport = createDiscoverTransport({ auth: session });
  await transport.loadRows({ mediaType: 'movie' });
  assert.equal(calls[0].path, '/api/v1/discover/');
  assert.equal(calls[0].options.query.media_type, 'movie');
  await transport.refresh({ mediaType: 'movie' });
  assert.equal(calls[1].path, '/api/v1/discover/refresh/');
  assert.equal(calls[1].options.method, 'POST');

  const rows = discoverRowsFromPayload({
    rows: [{
      key: 'top',
      title: 'Top',
      why: 'Because',
      items: [{ media_type: 'movie', source: 'tmdb', media_id: '1', title: 'Film', image: null, rating: 8, release_date: '2024-01-01' }],
    }],
  });
  assert.equal(rows[0].items[0].identity.source, 'tmdb');
  assert.equal(rows[0].items[0].lines[0].parts[0].text, '2024');
  assert.deepEqual(hiddenFromPayload({ results: [{ item_id: 3, title: 'Old', media_type: 'movie' }] })[0].itemId, 3);
});

test('library transport loads tracked media and maps table rows', async () => {
  const { calls, session } = authFixture(() => ({ pagination: { total: 1 }, results: [{
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
      title: 'The Quiet Orbit',
      image: 'https://example.com/show.jpg',
      runtime_minutes: 48,
      release_datetime: '2024-01-01T00:00:00Z',
      genres: ['Mystery'],
    },
  }] }));
  const transport = createLibraryTransport({ auth: session });
  await transport.load({ mediaType: 'tv', limit: 30 });
  const mediaCall = calls.find(call => call.path === '/api/v1/media/tv/');
  assert.ok(mediaCall, 'the library page is requested (after the date preferences)');
  assert.equal(mediaCall.options.query.limit, 30);

  const rows = mediaRowsFromPayload({ results: [{
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
      title: 'The Quiet Orbit',
      image: 'https://example.com/show.jpg',
      runtime_minutes: 48,
      release_datetime: '2024-01-01T00:00:00Z',
      genres: ['Mystery'],
    },
  }] });
  assert.equal(rows[0].cells.status.text, 'In progress');
  assert.equal(rows[0].cells.progress.maxText, ' / 10 episodes');
  assert.equal(rows[0].identity.source, undefined);
});

test('library transport PATCHes and deletes a tracked row by identity', async () => {
  const { calls, session } = authFixture(() => ({}));
  const transport = createLibraryTransport({ auth: session });
  await transport.update({
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '42' },
    values: { status: 'Completed', score: 9, start_date: '' },
  });
  assert.equal(calls[0].path, '/api/v1/media/movie/tmdb/42/');
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(calls[0].options.body, { status: 'Completed', score: 9, start_date: null });
  await transport.remove({ identity: { mediaType: 'movie', source: 'tmdb', mediaId: '42' } });
  assert.equal(calls[1].options.method, 'DELETE');
});

test('search transport reads sources, suggestions, results and parents from the search API', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/search/sources/') return { media_types: [{ display: 'All', value: 'all' }], barcode_types: ['book'], sources: [{ value: 'tmdb', label: 'TMDB' }], default_source: 'tmdb', labels: { search: 'Search' } };
    if (path === '/api/v1/search/suggestions/') return { suggestions: [{ id: '0', title: 'Dune', subtitle: 'Movie', image: null, url: '/details/tmdb/movie/1/dune' }] };
    return { sections: [] };
  });
  const transport = createSearchTransport({ auth: session });
  const bar = searchBarFromPayload(await transport.loadSources({ mediaType: 'movie' }));
  assert.equal(calls[0].options.query.media_type, 'movie');
  assert.equal(bar.sources[0].value, 'tmdb');
  assert.deepEqual(bar.barcodeTypes, ['book']);
  const suggestions = suggestionsFromPayload(await transport.loadSuggestions({ query: 'du', mediaType: 'all' }));
  assert.equal(calls[1].path, '/api/v1/search/suggestions/');
  assert.equal(suggestions[0].href, '/details/tmdb/movie/1/dune');
  await transport.loadResults({ query: 'dune', mediaType: 'movie', source: 'tmdb', page: 2, layout: 'list' });
  assert.equal(calls[2].path, '/api/v1/search/results/');
  assert.deepEqual(calls[2].options.query, { q: 'dune', media_type: 'movie', source: 'tmdb', page: 2, layout: 'list' });
  await transport.loadParents({ kind: 'tv', query: 'ab' });
  assert.equal(calls[3].path, '/api/v1/search/parents/');
  await transport.createMusic({ kind: 'artist', id: 'mb1' });
  assert.equal(calls[4].options.method, 'POST');
});

test('search transport is signed out without a session and says so', async () => {
  const transport = createSearchTransport({});
  assert.equal(transport.mode, 'local');
  await assert.rejects(() => transport.loadResults({ query: 'dune' }), /Sign in/);
});

test('collection transport groups copies and settings transport reads preferences', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/collection/') return { results: [{
      id: 5,
      media_type: '4K Blu-ray',
      resolution: '4K',
      hdr: 'Dolby Vision',
      audio_codec: 'Dolby Atmos',
      audio_channels: '7.1.4',
      bitrate: 80,
      is_3d: false,
      collected_at: '2026-10-01T00:00:00Z',
      item: { media_type: 'movie', library_media_type: 'movie', title: 'Dune', source: 'tmdb', media_id: '693134', image: null, release_datetime: '2024-03-01T00:00:00Z' },
    }] };
    return { preferences: {
      week_start_day: 'monday',
      session_duration: 604800,
      date_format: 'iso_8601',
      clickable_media_cards: true,
    }, choices: {} };
  });
  const collection = createCollectionTransport({ auth: session });
  await collection.load();
  assert.equal(calls[0].path, '/api/v1/collection/');
  const items = collectionItemsFromPayload({ results: [{
    id: 5,
    media_type: '4K Blu-ray',
    collected_at: '2026-10-01T00:00:00Z',
    item: { media_type: 'movie', library_media_type: 'movie', title: 'Dune', source: 'tmdb', media_id: '693134' },
  }] });
  assert.equal(items[0].format, '4K Blu-ray');
  assert.equal(items[0].copies.length, 1);

  const settings = createSettingsTransport({ auth: session });
  await settings.loadPreferences();
  assert.equal(calls[1].path, '/api/v1/user/preferences/');
  assert.deepEqual(preferencesToForm({ preferences: { week_start_day: 'sunday', session_duration: 86400 } }), {
    week_start_day: 'sunday',
    session_duration: '86400',
  });
  assert.equal(preferencesToForm({ preferences: { clickable_media_cards: true } }).clickable_media_cards, true);
  await settings.savePreferences({ clickable_media_cards: true });
  assert.equal(calls[2].path, '/api/v1/user/preferences/');
  assert.equal(calls[2].options.method, 'PATCH');
  assert.deepEqual(calls[2].options.body, { clickable_media_cards: true });
});

test('settings transport propagates preference save errors', async () => {
  const { session } = authFixture((path, options) => {
    if (path === '/api/v1/user/preferences/' && options.method === 'PATCH') {
      throw new Error('Preference update failed.');
    }
    return { preferences: { clickable_media_cards: false } };
  });
  const settings = createSettingsTransport({ auth: session });
  await assert.rejects(
    settings.savePreferences({ clickable_media_cards: true }),
    /Preference update failed\./,
  );
});

test('list items map tracked and untracked entries into list-detail rows', () => {
  const rows = listItemsFromPayload({
    items: {
      pagination: { total: 1 },
      results: [{
        item_id: 'movie/tmdb/1',
        status: 1,
        score: 8.5,
        progress: 1,
        progress_unit: 'plays',
        created_at: '2025-01-30T00:00:00Z',
        start_date: null,
        end_date: null,
        item: {
          media_type: 'movie',
          library_media_type: 'movie',
          title: 'Dune',
          image: 'https://example.com/dune.jpg',
          release_datetime: '2024-03-01T00:00:00Z',
        },
      }],
    },
  });
  assert.equal(rows[0].title, 'Dune');
  assert.equal(rows[0].status, 'In progress');
  assert.equal(rows[0].progressLabel, '1 play');
  assert.equal(rows[0].releaseLabel, '2024');
  assert.equal(rows[0].rank, 1);
});

test('mark unwatched asks the server to remove the most recent watch', async () => {
  const { calls, session } = authFixture();
  configureMediaCardTransport({ auth: session });
  try {
    const result = await unwatchEpisode({ mediaType: 'episode', source: 'tmdb', mediaId: '1399', seasonNumber: 1, episodeNumber: 3 });
    assert.deepEqual(result, { removed: true });
    assert.deepEqual(calls.map(call => [call.options.method, call.path]), [
      ['DELETE', '/api/v1/media/tv/tmdb/1399/1/episodes/3/watch/'],
    ]);
  } finally {
    resetMediaCardTransport();
  }
});

test('mark unwatched with no recorded watch removes nothing', async () => {
  const { session } = authFixture(() => {
    const error = new Error('Episode has no watches.');
    error.status = 404;
    throw error;
  });
  configureMediaCardTransport({ auth: session });
  try {
    assert.deepEqual(
      await unwatchEpisode({ mediaType: 'episode', source: 'tmdb', mediaId: '1399', seasonNumber: 1, episodeNumber: 3 }),
      { removed: false },
    );
  } finally {
    resetMediaCardTransport();
  }
});
