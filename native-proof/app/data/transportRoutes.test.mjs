import assert from 'node:assert/strict';
import test from 'node:test';
import { createCalendarTransport } from './calendarTransport.js';
import {
  createStatisticsTransport,
  flattenStatisticsModel,
} from './statisticsTransport.js';
import { createListTransport } from './listTransport.js';
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
