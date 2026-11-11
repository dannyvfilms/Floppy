import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createRemoteHistoryActions,
  historyDaysFromPayload,
  historySavedViewQuery,
  sessionQuery,
} from './historyTransportCore.js';

const movie = {
  entry_key: '7',
  instance_id: 7,
  media_type: 'movie',
  display_title: 'A very long movie title that keeps going and going and going',
  played_at_local: '2026-11-09T20:15:00-06:00',
  runtime_display: '2h 1min',
  runtime_minutes: 121,
  score: 8,
  status: 'Completed',
  item: { media_id: '603', source: 'tmdb', media_type: 'movie', title: 'Dune' },
};
const episode = {
  entry_key: '9',
  instance_id: 9,
  media_type: 'episode',
  title: 'Pilot',
  episode_code: 'S01E01',
  played_at_local: '2026-11-09T19:00:00-06:00',
  item: { media_id: '1', source: 'tmdb', media_type: 'episode', season_number: 1, episode_number: 1 },
};
const book = { entry_key: 'book-3', instance_id: 3, media_type: 'book', title: 'Dune', played_at_local: '2026-11-09T10:00:00-06:00' };

test('days keep the server labels, runtime and overflow counts', () => {
  const [day] = historyDaysFromPayload({
    results: [{
      date: '2026-11-09',
      weekday: 'Monday',
      date_display: 'November 9, 2026',
      total_runtime_display: '2h 1min',
      entry_count: 45,
      entries: [movie],
    }],
  });
  assert.equal(day.key, '2026-11-09');
  assert.equal(day.weekday, 'Monday');
  assert.equal(day.dateLabel, 'November 9, 2026');
  assert.equal(day.runtimeLabel, '2h 1min');
  assert.equal(day.hasMore, true);
  assert.equal(day.remaining, 44);
  assert.equal(day.entries[0].date, '2026-11-09');
});

test('a zero runtime and missing counts read as empty and complete', () => {
  const [day] = historyDaysFromPayload({ results: [{ date: '2026-11-09', total_runtime_display: '0min', entries: [book] }] });
  assert.equal(day.runtimeLabel, '');
  assert.equal(day.hasMore, false);
  assert.equal(day.entryCount, 1);
  assert.deepEqual(historyDaysFromPayload({}), []);
});

test('entries expose delete and edit rights per media type', () => {
  const [day] = historyDaysFromPayload({ results: [{ date: '2026-11-09', entries: [movie, episode, book] }] });
  const [m, e, b] = day.entries;
  assert.equal(m.canDelete, true);
  assert.deepEqual(m.editFields, ['date', 'score', 'status']);
  assert.equal(e.canDelete, true);
  assert.deepEqual(e.editFields, ['date']);
  assert.equal(b.canDelete, false);
  assert.equal(b.canEdit, true);
  assert.equal(m.instanceId, 7);
});

test('entry notes lose their tags, nested ones included', () => {
  const notes = ['<p>Great <b>film</b></p>', '<scr<script>ipt>alert(1)</scr</script>ipt>', 'a <<b>i>b</<b>i> c', 'plain note'];
  const [day] = historyDaysFromPayload({ results: [{ date: '2026-11-09', entries: notes.map(note => ({ ...movie, notes: note })) }] });
  assert.deepEqual(day.entries.map(entry => entry.sessions[0].note), ['Great film', 'ipt>alert(1)ipt>', 'a i>bi> c', 'plain note']);
  day.entries.forEach(entry => assert.doesNotMatch(entry.sessions[0].note, /<[^>]*>/));
});

test('an entry without an instance id cannot be edited or deleted', () => {
  const [day] = historyDaysFromPayload({ results: [{ date: '2026-11-09', entries: [{ ...movie, instance_id: null }] }] });
  assert.equal(day.entries[0].canEdit, false);
  assert.equal(day.entries[0].canDelete, false);
});

test('session filters match the web activity dialog', () => {
  assert.deepEqual(sessionQuery({ mediaType: 'movie', item: movie.item }), { media_type: 'movie', media_id: '603', source: 'tmdb' });
  assert.deepEqual(
    sessionQuery({ mediaType: 'episode', item: episode.item }),
    { media_type: 'tv', media_id: '1', source: 'tmdb', season_number: 1 },
  );
  assert.deepEqual(sessionQuery({ mediaType: 'music', album: { id: 5 }, item: {} }), { album: 5 });
  assert.deepEqual(sessionQuery({ mediaType: 'podcast', show: { id: 2 }, item: {} }), { media_type: 'podcast', podcast_show: 2 });
  assert.equal(sessionQuery({ mediaType: 'game', item: { media_id: '1', source: 'igdb' } }).logging_style, 'sessions');
});

test('saved view query uses the web filter names', () => {
  assert.equal(
    historySavedViewQuery({ from: '2026-01-01', mediaTypes: ['movie', 'tv'], mode: 'release', genres: ['Drama'] }),
    'start-date=2026-01-01&media_type=movie%2Ctv&history_mode=release&genre=Drama',
  );
  assert.equal(historySavedViewQuery({ mode: 'activity' }), '');
});

test('remote actions call the /api/v1 history routes', async () => {
  const calls = [];
  const actions = createRemoteHistoryActions(async (path, options) => { calls.push([path, options]); return {}; });
  await actions.loadGenreOptions();
  await actions.loadSessions({ mediaType: 'movie', item: movie.item });
  await actions.loadDay({ dayKey: '2026-11-09', offset: 30, mediaTypes: ['movie'] });
  await actions.loadRelease({ from: '2026-11-01', to: '2026-11-30' });
  await actions.updateEntry({ mediaType: 'movie', instanceId: 7, date: '2026-11-09T20:15', score: 9 });
  await actions.deleteEntry({ mediaType: 'movie', instanceId: 7 });
  await actions.saveView({ name: 'Movies', query: 'media_type=movie' });
  assert.equal(calls[0][0], '/api/v1/history/genres/');
  assert.equal(calls[1][0], '/api/v1/history/sessions/');
  assert.equal(calls[2][0], '/api/v1/history/days/20261109/');
  assert.deepEqual(calls[2][1].query, { media_type: 'movie', entry_offset: 30 });
  assert.equal(calls[3][0], '/api/v1/history/release/');
  assert.deepEqual(calls[3][1].query, { start_date: '2026-11-01', end_date: '2026-11-30' });
  assert.deepEqual(calls[4], ['/api/v1/history/entries/movie/7/', { method: 'PATCH', body: { date: '2026-11-09T20:15', score: 9 } }]);
  assert.deepEqual(calls[5], ['/api/v1/history/entries/movie/7/', { method: 'DELETE' }]);
  assert.deepEqual(calls[6], ['/api/v1/history/saved-views/', { method: 'POST', body: { name: 'Movies', query: 'media_type=movie' } }]);
});

test('release days are requested one page at a time', async () => {
  const calls = [];
  const actions = createRemoteHistoryActions(async (path, options) => { calls.push([path, options]); return {}; });
  await actions.loadRelease({ mediaTypes: ['movie'], limit: 31, offset: 62 });
  assert.equal(calls[0][0], '/api/v1/history/release/');
  assert.deepEqual(calls[0][1].query, { media_type: 'movie', limit: 31, offset: 62 });
});
