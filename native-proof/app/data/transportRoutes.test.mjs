import assert from 'node:assert/strict';
import test from 'node:test';
import { createCalendarTransport } from './calendarTransport.js';
import { createHistoryTransport, historyEntriesFromPayload } from './historyTransport.js';
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
