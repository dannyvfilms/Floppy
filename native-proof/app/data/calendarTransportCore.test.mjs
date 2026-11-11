import assert from 'node:assert/strict';
import test from 'node:test';
import {
  calendarModelFromPayload,
  calendarOptionsFromEvents,
  calendarOptionsFromLinks,
  createRemoteCalendarActions,
  releaseFromEvent,
} from './calendarTransportCore.js';

const episodeEvent = {
  id: 7,
  datetime: '2026-11-09T18:30:00Z',
  content_number: 4,
  release_type: '',
  item: { media_type: 'episode', title: 'Show', season_number: 2, episode_number: 4 },
};

test('an API episode event is a season-type release with an SxxEyy label', () => {
  const release = releaseFromEvent({ ...episodeEvent, viewer_status: 'In progress' });
  assert.equal(release.mediaType, 'season');
  assert.equal(release.episodeLabel, 'S02E04');
  assert.equal(release.status, 'In progress');
});

test('model keeps episode releases on their day', () => {
  const model = calendarModelFromPayload({ results: [episodeEvent] }, { month: 11, year: 2026 });
  assert.equal(model.total, 1);
  assert.equal(Object.values(model.releases).flat().length, 1);
});

test('readAll merges viewer statuses and survives a statuses failure', async () => {
  const calls = [];
  const request = async (path, options) => {
    calls.push(path);
    if (path === '/api/v1/calendar/statuses/') return { statuses: { 7: 'Completed' } };
    return { results: [episodeEvent], pagination: { total: 1 } };
  };
  const actions = createRemoteCalendarActions(request);
  const merged = await actions.readAll({ month: 11, year: 2026 });
  assert.equal(merged.results[0].viewer_status, 'Completed');
  const failing = createRemoteCalendarActions(async path => {
    if (path.includes('statuses')) throw new Error('nope');
    return { results: [episodeEvent], pagination: { total: 1 } };
  });
  const plain = await failing.readAll({ month: 11, year: 2026 });
  assert.equal(plain.results[0].viewer_status, undefined);
  assert.ok(calls.includes('/api/v1/calendar/links/') === false);
});

test('week start saves through the user preferences route', async () => {
  const seen = [];
  const actions = createRemoteCalendarActions(async (path, options) => { seen.push([path, options]); return {}; });
  await actions.saveWeekStart('sunday');
  assert.deepEqual(seen[0], ['/api/v1/user/preferences/', { method: 'PATCH', body: { week_start_day: 'sunday' } }]);
});

test('options come from the links payload with in-month status flags', () => {
  const releases = { 9: [{ mediaType: 'movie', status: 'Planning' }] };
  const options = calendarOptionsFromLinks({
    filter_media_types: [{ value: 'movie', label: 'Movies' }],
    filter_statuses_by_type: { movie: ['Planning', 'Completed'] },
    statuses: [{ value: 'Planning', label: 'Planning' }, { value: 'Completed', label: 'Completed' }],
    release_types: [{ value: 'digital', label: 'Digital' }],
    release_base_url: 'https://x/calendar/t.ics',
    history_base_url: 'https://x/history/t.ics',
    week_start_day: 'sunday',
    region_unset: true,
  }, releases);
  assert.equal(options.statusesByType.movie[0].inMonth, true);
  assert.equal(options.statusesByType.movie[1].inMonth, false);
  assert.equal(options.weekStartDay, 'sunday');
  assert.equal(options.regionUnset, true);
  assert.equal(options.linksProps.releaseBaseUrl, 'https://x/calendar/t.ics');
  assert.equal(calendarOptionsFromLinks(null), null);
});

test('fallback options use only what the events carry', () => {
  const options = calendarOptionsFromEvents({ 1: [{ mediaType: 'tv', releaseType: 'digital' }] });
  assert.deepEqual(options.mediaTypes.map(item => item.value), ['tv']);
  assert.deepEqual(options.releaseTypes.map(item => item.value), ['digital']);
  assert.equal(options.linksProps, null);
});
