import assert from 'node:assert/strict';
import test from 'node:test';
import {
  calendarModelFromPayload,
  calendarOptionsFromEvents,
  calendarOptionsFromLinks,
  calendarQuery,
  createRemoteCalendarActions,
  monthGrid,
  releaseFromEvent,
  releasesByDay,
} from './calendarTransportCore.js';

test('calendarQuery prefers an explicit date range over month and year', () => {
  assert.deepEqual(calendarQuery(), {});
  assert.deepEqual(calendarQuery({ month: 3, year: 2026 }), { month: 3, year: 2026 });
  assert.deepEqual(
    calendarQuery({ startDate: '2026-03-01', endDate: '2026-03-31' }),
    { start_date: '2026-03-01', end_date: '2026-03-31' },
  );
  assert.deepEqual(calendarQuery({ startDate: '2026-03-01' }), {});
});

test('monthGrid pads leading and trailing cells for leap and common Februaries', () => {
  const leap = monthGrid(2, 2024);
  assert.equal(leap.daysInMonth, 29);
  assert.equal(leap.days.length, 29);
  assert.deepEqual(leap.weeks[0], [0, 0, 0, 1, 2, 3, 4]);
  assert.equal(leap.weeks.length, 5);
  const sunday = monthGrid(2, 2026, 'sunday');
  assert.deepEqual(sunday.weeks[0][0], 1);
  assert.equal(sunday.weeks.length, 4);
});

test('releaseFromEvent survives an event with no datetime or item', () => {
  const release = releaseFromEvent({});
  assert.equal(release.day, null);
  assert.equal(release.subtitle, 'Time unknown');
  assert.equal(release.mediaLabel, '');
  assert.equal(release.image, null);
  assert.equal(release.poster, null);
  assert.equal(release.sortTime, 0);
});

test('releaseFromEvent flags the 11:59:59 sentinel as an unknown time', () => {
  const release = releaseFromEvent({
    id: 1,
    datetime: '2026-03-15T11:59:59',
    item: { media_type: 'movie', title: 'M' },
  });
  assert.equal(release.unknownTime, true);
  assert.equal(release.eventTime, '');
  assert.equal(release.subtitle, 'Time unknown');
  assert.equal(release.day, 15);
});

test('releaseFromEvent labels an episode from the season and episode numbers', () => {
  const release = releaseFromEvent({
    id: 2,
    datetime: '2026-03-15T20:30:00',
    item: {
      media_type: 'episode',
      title: 'Show',
      season_number: 2,
      episode_number: 7,
      image: null,
    },
  });
  assert.equal(release.mediaType, 'season');
  assert.equal(release.mediaLabel, 'TV Season');
  assert.equal(release.episodeLabel, 'S02E07');
  assert.equal(release.eventTime, 'at 8:30 PM');
  assert.equal(release.subtitle, 'S02E07 at 8:30 PM');
  assert.equal(release.image, null);
});

test('releaseFromEvent builds the digital release subtitle and card lines', () => {
  const release = releaseFromEvent({
    id: 3,
    datetime: '2026-01-02T09:05:00',
    release_type: 'digital',
    item: { media_type: 'movie', title: 'Film', runtime_minutes: 120, release_datetime: '2026-01-02T00:00:00Z' }, // the year line comes from item.release_datetime
  });
  assert.equal(release.releaseTypeLabel, 'Digital');
  assert.equal(release.subtitle, 'Digital release at 9:05 AM');
  assert.deepEqual(release.cardLines, ['2026', '120 min']);
});

test('releasesByDay groups by local day, skips undated events and sorts unknown times last', () => {
  const grouped = releasesByDay([
    { id: 1, datetime: '2026-03-15T09:00:00', item: { media_type: 'movie', title: 'Early' } },
    { id: 2, datetime: '2026-03-15T11:59:59', item: { media_type: 'movie', title: 'Unknown' } },
    { id: 3, datetime: 'not-a-date', item: { media_type: 'movie', title: 'Bad' } },
  ]);
  assert.deepEqual(Object.keys(grouped), ['15']);
  assert.deepEqual(grouped['15'].map(release => release.title), ['Early', 'Unknown']);
  assert.deepEqual(releasesByDay([]), {});
});

test('calendarModelFromPayload builds the grid, labels and a selected day', () => {
  const model = calendarModelFromPayload([], { month: 3, year: 2026, today: new Date(2026, 4, 10) });
  assert.equal(model.monthName, 'March');
  assert.equal(model.empty, true);
  assert.equal(model.total, 0);
  assert.equal(model.selectedDay, 1);
  assert.deepEqual(model.weekdayHeaders, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']);
  assert.equal(model.weeks.length, 6);
  assert.equal(model.dayLabels['1'], 'Sunday');
  assert.deepEqual(model.today, { day: 10, month: 5, year: 2026 });
});

test('calendarModelFromPayload selects the earliest release day outside the current month', () => {
  const model = calendarModelFromPayload({
    results: [
      { id: 1, datetime: '2026-03-10T09:00:00', item: { media_type: 'movie', title: 'A' } },
      { id: 2, datetime: '2026-03-03T09:00:00', item: { media_type: 'movie', title: 'B' } },
    ],
  }, { month: 3, year: 2026, today: new Date(2026, 4, 10) });
  assert.equal(model.selectedDay, 3);
  assert.equal(model.empty, false);
  assert.equal(Object.keys(model.releases).length, 2);
});

test('calendarOptionsFromEvents falls back to the types the events actually use', () => {
  assert.deepEqual(calendarOptionsFromEvents({}).mediaTypes, []);
  assert.deepEqual(calendarOptionsFromEvents({}).linksProps, null);
  const options = calendarOptionsFromEvents({
    5: [{ mediaType: 'banana', releaseType: 'digital', status: 'Planning' }],
  });
  assert.deepEqual(options.mediaTypes, [
    { value: 'banana', label: 'banana', shortLabel: 'banana' },
  ]);
  assert.deepEqual(options.releaseTypes, [{ value: 'digital', label: 'Digital' }]);
  assert.deepEqual(options.initialFilters.selectedTypes, ['banana']);
  assert.equal(options.weekStartDay, null);
});

test('calendarOptionsFromLinks maps nothing without a links payload and defaults otherwise', () => {
  assert.equal(calendarOptionsFromLinks(null), null);
  const options = calendarOptionsFromLinks({});
  assert.deepEqual(options.mediaTypes, []);
  assert.deepEqual(options.statusesByType, {});
  assert.equal(options.weekStartDay, 'monday');
  assert.equal(options.linksProps.releaseBaseUrl, '');
});

test('readAll pages with the offset from the next link and merges viewer statuses', async () => {
  const events = [
    { id: 1, datetime: '2026-03-10T09:00:00', item: { media_type: 'movie', title: 'A' } },
    { id: 2, datetime: '2026-03-11T09:00:00', item: { media_type: 'movie', title: 'B' } },
  ];
  const calls = [];
  let read = 0;
  const transport = createRemoteCalendarActions(async (path, options) => {
    calls.push({ path, options });
    if (path === '/api/v1/calendar/statuses/') return { statuses: { 2: 'Completed' } };
    read += 1;
    return read === 1
      ? { results: [events[0]], pagination: { total: 2, next: '/api/v1/calendar/?limit=200&offset=200' } }
      : { results: [events[1]], pagination: { total: 2, next: null } };
  });
  const payload = await transport.readAll({ month: 3, year: 2026 });
  assert.equal(payload.results.length, 2);
  assert.equal(payload.results[1].viewer_status, 'Completed');
  assert.equal(payload.results[0].viewer_status, undefined);
  assert.deepEqual(payload.pagination, { total: 2 });
  assert.equal(calls[1].options.query.offset, 200);
  assert.equal(calls[2].path, '/api/v1/calendar/statuses/');
  assert.deepEqual(calls[2].options.query, { month: 3, year: 2026 });
});
