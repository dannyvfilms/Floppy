import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createRemoteHistoryActions,
  genreOptionsFromPayload,
  historyDaysFromPayload,
  historyEntriesFromPayload,
  historyMonthNav,
  historyQuery,
  historySavedViewQuery,
  monthBounds,
  monthKey,
  monthPrefix,
  sessionQuery,
  shiftMonth,
  todayKey,
} from './historyTransportCore.js';

test('historyQuery only sends the filters that are actually set', () => {
  assert.deepEqual(historyQuery(), {});
  assert.deepEqual(historyQuery({ mediaTypes: [], limit: undefined, offset: undefined }), {});
  assert.deepEqual(historyQuery({ mediaTypes: ['tv', 'movie'] }), { media_type: 'tv,movie' });
  assert.deepEqual(
    historyQuery({ from: '2026-01-01', to: '2026-02-01', genre: 'comedy', impliedGenre: 'heist' }),
    { start_date: '2026-01-01', end_date: '2026-02-01', genre: 'comedy', implied_genre: 'heist' },
  );
  assert.deepEqual(historyQuery({ limit: 5, offset: 10, maxEntriesPerDay: 3 }), {
    limit: 5, offset: 10, max_entries_per_day: 3,
  });
});

test('historyEntriesFromPayload accepts every accepted payload shape', () => {
  assert.deepEqual(historyEntriesFromPayload(undefined), []);
  const day = { date: '2026-01-02', entries: [{ media_type: 'tv', title: 'Show' }] };
  assert.equal(historyEntriesFromPayload({ results: [day] }).length, 1);
  assert.equal(historyEntriesFromPayload({ days: [day] }).length, 1);
  assert.equal(historyEntriesFromPayload([day]).length, 1);
});

test('a bare entry falls back to the day date, the movie type and read-only flags', () => {
  const [entry] = historyEntriesFromPayload([{ date: '2026-01-02', entries: [{}] }]);
  assert.equal(entry.mediaType, 'movie');
  assert.equal(entry.date, '2026-01-02');
  assert.equal(entry.time, '00:00');
  assert.equal(entry.when, '2026-01-02 00:00');
  assert.equal(entry.whenValue, '2026-01-02T00:00');
  assert.equal(entry.verb, 'Watched');
  assert.equal(entry.title, '');
  assert.deepEqual(entry.editFields, ['date', 'score', 'status']); // movies have editable fields; canEdit still needs an instance_id
  assert.equal(entry.canEdit, false);
  assert.equal(entry.canDelete, false);
  assert.equal(entry.key, '2026-01-02-0');
  assert.deepEqual(entry.image, { src: null, fallback: '', source: 'primary' });
  assert.deepEqual(entry.sessions, [{
    key: '0-session',
    date: '2026-01-02',
    when: '2026-01-02 00:00',
    label: 'Watched',
    runtime: '',
    runtimeMinutes: 0,
    score: null,
    note: '',
  }]);
});

test('episodes are editable and deletable, unknown media types are not', () => {
  const [episode] = historyEntriesFromPayload([{
    date: '2026-01-02',
    entries: [{
      entry_key: 'e9',
      media_type: 'episode',
      played_at_local: '2026-01-02T05:06',
      instance_id: 7,
      item: { media_type: 'episode', media_id: '5', source: 'tmdb', season_number: 2 },
    }],
  }]);
  assert.equal(episode.key, 'e9');
  assert.equal(episode.time, '05:06');
  assert.deepEqual(episode.editFields, ['date']);
  assert.equal(episode.canEdit, true);
  assert.equal(episode.canDelete, true);
  assert.equal(episode.subtitle, '');
  const [unknown] = historyEntriesFromPayload([{
    date: '2026-01-02',
    entries: [{ media_type: 'banana', instance_id: 8 }],
  }]);
  assert.equal(unknown.verb, 'Watched');
  assert.equal(unknown.editFields, null);
  assert.equal(unknown.canEdit, false);
  assert.equal(unknown.canDelete, false);
});

test('historyDaysFromPayload reports overflow counts and hides zero runtimes', () => {
  assert.deepEqual(historyDaysFromPayload(undefined), []);
  const days = historyDaysFromPayload({
    results: [
      { date: '2026-01-02', entry_count: '5', total_runtime_display: '0 min', entries: [{}] },
      { day_key: '2026-01-03', entry_count: 1, total_runtime_display: '1h 20m', entries: [] },
      { entry_count: 0, entries: [] },
    ],
  });
  assert.equal(days[0].key, '2026-01-02');
  assert.equal(days[0].entryCount, 5);
  assert.equal(days[0].hasMore, true);
  assert.equal(days[0].remaining, 4);
  assert.equal(days[0].runtimeLabel, '');
  assert.equal(days[1].key, '2026-01-03');
  assert.equal(days[1].runtimeLabel, '1h 20m');
  assert.equal(days[1].remaining, 1);
  assert.equal(days[2].key, 'day-2');
  assert.equal(days[2].hasMore, false);
});

test('sessionQuery addresses music, podcasts, shows and sessions', () => {
  assert.deepEqual(sessionQuery({ mediaType: 'music', album: { id: 3 } }), { album: 3 });
  assert.deepEqual(
    sessionQuery({ mediaType: 'podcast', show: { id: 9 } }),
    { media_type: 'podcast', podcast_show: 9 },
  );
  assert.deepEqual(
    sessionQuery({ mediaType: 'episode', item: { media_id: '5', source: 'tmdb', season_number: 0 } }),
    { media_type: 'tv', media_id: '5', source: 'tmdb' },
  );
  assert.deepEqual(
    sessionQuery({ mediaType: 'game', item: { media_id: '6', source: 'steam' } }),
    { media_type: 'game', media_id: '6', source: 'steam', logging_style: 'sessions' },
  );
  assert.deepEqual(sessionQuery({ mediaType: 'movie', item: {} }), { media_type: 'movie' });
});

test('historySavedViewQuery joins the chosen filters and skips activity mode', () => {
  assert.equal(historySavedViewQuery({}), '');
  assert.equal(historySavedViewQuery({ mode: 'activity' }), '');
  assert.equal(
    historySavedViewQuery({
      from: '2026-01-01', to: '2026-02-01', mediaTypes: ['tv'],
      mode: 'sessions', genres: ['a', 'b'], impliedGenres: ['x'],
    }),
    'start-date=2026-01-01&end-date=2026-02-01&media_type=tv&history_mode=sessions&genre=a%2Cb&implied_genre=x',
  );
});

test('genreOptionsFromPayload trims, drops blanks and rejects non-arrays', () => {
  assert.deepEqual(genreOptionsFromPayload(undefined), { genres: [], impliedGenres: [] });
  assert.deepEqual(
    genreOptionsFromPayload({ genres: ['a', ' b ', '', 7], implied_genres: 'x' }),
    { genres: ['a', 'b', '7'], impliedGenres: [] },
  );
});

test('month helpers cross year boundaries and bound leap Februaries', () => {
  assert.deepEqual(monthKey(new Date(2026, 2, 5)), { year: 2026, month: 3 });
  assert.equal(monthPrefix({ year: 2026, month: 3 }), '2026-03');
  assert.deepEqual(shiftMonth({ year: 2026, month: 1 }, -1), { year: 2025, month: 12 });
  assert.deepEqual(shiftMonth({ year: 2025, month: 12 }, 1), { year: 2026, month: 1 });
  assert.deepEqual(monthBounds({ year: 2024, month: 2 }), { from: '2024-02-01', to: '2024-02-29' });
  assert.equal(todayKey(new Date(2026, 2, 5)), '2026-03-05');
});

test('historyMonthNav blocks forward navigation at the current month', () => {
  const current = historyMonthNav({ year: 2026, month: 3 }, new Date(2026, 2, 10));
  assert.equal(current.monthLabel, 'March');
  assert.equal(current.previousYear.label, '2025');
  assert.equal(current.previousMonth.label, 'Feb');
  assert.equal(current.nextMonth.disabled, true);
  assert.equal(current.currentMonth.disabled, true);
  const past = historyMonthNav({ year: 2026, month: 1 }, new Date(2026, 2, 10));
  assert.equal(past.previousMonth.label, 'Dec');
  assert.equal(past.nextMonth.disabled, false);
  assert.equal(past.currentMonth.disabled, false);
});

test('remote history actions build entry bodies and day routes', async () => {
  const calls = [];
  const transport = createRemoteHistoryActions(async (path, options) => {
    calls.push({ path, options });
    return {};
  });
  await transport.updateEntry({ mediaType: 'movie', instanceId: 5, score: 0, status: '' });
  assert.equal(calls[0].path, '/api/v1/history/entries/movie/5/');
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(calls[0].options.body, { score: 0 });
  await transport.deleteEntry({ mediaType: 'tv', instanceId: 'a/b' });
  assert.equal(calls[1].path, '/api/v1/history/entries/tv/a%2Fb/');
  assert.equal(calls[1].options.method, 'DELETE');
  await transport.loadDay({ dayKey: '2026-01-02', offset: 20, limit: 5, mediaTypes: ['movie'] });
  assert.equal(calls[2].path, '/api/v1/history/days/20260102/');
  assert.deepEqual(calls[2].options.query, { media_type: 'movie', entry_offset: 20 });
});

test('a link into History keeps only the filters the page reads', async () => {
  const { parseHistoryFilterUrl, historyQuery } = await import('./historyTransportCore.js');
  const scope = parseHistoryFilterUrl('/history?person_source=tmdb&person_id=12&junk=1&album=');
  assert.deepEqual(scope, { person_source: 'tmdb', person_id: '12' });
  assert.deepEqual(parseHistoryFilterUrl('?album=4'), { album: '4' });
  assert.deepEqual(parseHistoryFilterUrl(null), {});
  assert.equal(historyQuery({ scope, limit: 5 }).person_id, '12');
});
