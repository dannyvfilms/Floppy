import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createRemoteStatisticsActions,
  featuredFromPerson,
  statisticsModelFromPayload,
  talentFromPayload,
} from './statisticsTransportCore.js';

function recorder() {
  const calls = [];
  const request = async (path, options) => { calls.push({ path, options }); return {}; };
  return { calls, actions: createRemoteStatisticsActions(request) };
}

const comparison = {
  title: 'Comparison',
  copy: 'Hours in this range compared with previous period.',
  selected: 'previous_period',
  options: [{ value: 'previous_period', label: 'Previous period' }, { value: 'none', label: 'No comparison' }],
  rangeLabel: 'Jan 1 - Dec 31, 2025',
  rows: [{ key: 'movie', type: 'movie', label: 'Movie', currentLabel: '4h', comparisonLabel: '3h', deltaLabel: '+33%', state: 'up' }],
  total: { label: '+20%', state: 'up', periodLabel: 'last year', details: '' },
};

const overview = {
  range: { range_name: 'Last 30 Days', start_date: '2026-10-11T00:00:00-05:00', end_date: '2026-11-09T23:59:59-06:00', label: 'Oct 11 - Nov 9' },
  building: true,
  comparison,
  media_types: { available: ['movie', 'tv'], selected: ['movie'] },
  statistics: { summary_stats_by_type: { all: { total: 5 }, movie: { total: 3 }, game: { total: 2 } } },
};

test('overview reads the server range, gate, comparison and building flag', () => {
  const model = statisticsModelFromPayload(overview, []);
  assert.deepEqual(model.range, { name: 'Last 30 Days', startDate: '2026-10-11', endDate: '2026-11-09', label: 'Oct 11 - Nov 9' });
  assert.deepEqual(model.mediaTypeOptions.map(item => item.value), ['movie', 'tv']);
  assert.deepEqual(model.selectedMediaTypes, ['movie']);
  assert.equal(model.building, true);
  assert.equal(model.comparison.selected, 'previous_period');
  assert.equal(model.comparison.rows[0].deltaLabel, '+33%');
  assert.equal(model.summary.comparison.label, '+20%');
  assert.equal(model.summary.comparison.periodLabel, 'last year');
});

test('a single media type reads its own comparison row', () => {
  const model = statisticsModelFromPayload(overview, ['movie']);
  assert.equal(model.summary.comparison.label, '+33%');
  assert.equal(model.summary.comparison.periodLabel, 'last year');
});

test('without a server gate the summary keys offer the types and no comparison renders', () => {
  const model = statisticsModelFromPayload({ statistics: overview.statistics }, []);
  assert.deepEqual(model.mediaTypeOptions.map(item => item.value), ['movie', 'game']);
  assert.deepEqual(model.comparison, {});
  assert.equal(model.range.name, '');
});

test('talent maps the web section models and drops studio colours', () => {
  const talent = talentFromPayload({
    talent: {
      roleLeaders: { columns: [] },
      studioFootprint: { studios: [{ name: 'A24', color: '#6366f1' }] },
      tasteSignals: { sortOptions: [] },
    },
  });
  assert.equal(talent.studioFootprint.studios[0].color, undefined);
  assert.equal(talentFromPayload(null), null);
  assert.equal(talentFromPayload({ talent: 'nope' }), null);
});

test('featured person maps the server dict and hides the placeholder image', () => {
  const person = featuredFromPerson({
    name: 'Person', image: '/static/img/none.svg', unique_titles: 7, unique_movies: 4, unique_shows: 3,
    pct_of_library: 12, known_for_pills: [{ label: 'Actor', classes: 'x' }], source: 'tmdb', person_id: 5,
  });
  assert.equal(person.image, '');
  assert.equal(person.uniqueTitles, 7);
  assert.equal(person.personId, '5');
  assert.deepEqual(person.knownFor, [{ label: 'Actor' }]);
  assert.equal(featuredFromPerson(null), null);
});

test('range and compare ride the query; named ranges drop explicit dates', async () => {
  const { calls, actions } = recorder();
  await actions.loadModel();
  await actions.loadModel({ rangeName: 'This Year', startDate: '2026-01-01', endDate: '2026-11-09', compare: 'last_year' });
  await actions.loadModel({ startDate: '2026-02-01', endDate: '2026-02-28' });
  await actions.loadTalent({ rangeName: 'All Time' });
  assert.equal(calls[0].path, '/api/v1/statistics/overview/');
  assert.equal(calls[1].path, '/api/v1/statistics/overview/?range_name=This+Year&compare=last_year');
  assert.equal(calls[2].path, '/api/v1/statistics/overview/?start_date=2026-02-01&end_date=2026-02-28');
  assert.equal(calls[3].path, '/api/v1/statistics/talent/?range_name=All+Time');
});

test('preferences and featured person use the /api/v1 statistics routes', async () => {
  const { calls, actions } = recorder();
  await actions.loadPreferences();
  await actions.saveMediaTypes({ mediaTypes: [] });
  await actions.saveCompareMode({ compareMode: 'none' });
  await actions.saveDefaultRange({ rangeName: 'This Month' });
  await actions.saveGenreSort({ sortBy: 'plays' });
  await actions.selectFeaturedPerson({ source: 'tmdb', personId: '5', rangeName: 'This Month', sortBy: 'time' });
  assert.equal(calls[0].path, '/api/v1/statistics/preferences/');
  assert.deepEqual(calls[1].options, { method: 'PATCH', body: { media_types: [] } });
  assert.deepEqual(calls[2].options.body, { compare_mode: 'none' });
  assert.deepEqual(calls[3].options.body, { default_range: 'This Month' });
  assert.deepEqual(calls[4].options.body, { genre_sort_by: 'plays' });
  assert.equal(calls[5].path, '/api/v1/statistics/featured-person/');
  assert.deepEqual(calls[5].options.body, { person_source: 'tmdb', person_id: '5', sort_by: 'time', range_name: 'This Month' });
});
