// Anime Seasons: FilterBar intents and season steps become the next page query
// the same way on web (a URL) and native (an API call).
import assert from 'node:assert/strict';
import test from 'node:test';
import { animeSeasonsParams, applyAnimeSeasonsIntent } from '../frontend/pages/useAnimeSeasonsPage.js';

const query = { year: 2026, season: 'fall', format: 'all', sort: 'score', direction: 'desc', statuses: [] };

test('Filters sections set the season, year and format', () => {
  assert.equal(applyAnimeSeasonsIntent(query, { type: 'field', key: 'season', value: 'spring' }).season, 'spring');
  assert.equal(applyAnimeSeasonsIntent(query, { type: 'field', key: 'season_year', value: '2001' }).year, '2001');
  assert.equal(applyAnimeSeasonsIntent(query, { type: 'field', key: 'format', value: 'movie' }).format, 'movie');
});

test('clearing a section or all filters hands the default back to the server', () => {
  assert.equal('format' in applyAnimeSeasonsIntent(query, { type: 'clearField', key: 'format' }), false);
  assert.deepEqual(applyAnimeSeasonsIntent(query, { type: 'clear' }), {});
});

test('a new sort drops the direction so the sort starts in its natural order', () => {
  const next = applyAnimeSeasonsIntent(query, { type: 'set', key: 'sort', value: 'title' });
  assert.equal(next.sort, 'title');
  assert.equal('direction' in next, false);
  assert.equal(applyAnimeSeasonsIntent(query, { type: 'set', key: 'direction', value: 'asc' }).direction, 'asc');
});

test('statuses toggle and clear', () => {
  const one = applyAnimeSeasonsIntent(query, { type: 'toggle', key: 'statuses', value: 'untracked' });
  assert.deepEqual(one.statuses, ['untracked']);
  assert.deepEqual(applyAnimeSeasonsIntent(one, { type: 'toggle', key: 'statuses', value: 'untracked' }).statuses, []);
  assert.deepEqual(applyAnimeSeasonsIntent(one, { type: 'set', key: 'statuses', value: [] }).statuses, []);
});

test('a season step keeps the other filters', () => {
  const next = applyAnimeSeasonsIntent({ ...query, format: 'tv' }, { type: 'step', year: 2027, season: 'winter' });
  assert.deepEqual([next.year, next.season, next.format], [2027, 'winter', 'tv']);
});

test('an unknown intent leaves the query untouched', () => {
  assert.equal(applyAnimeSeasonsIntent(query, { type: 'range', key: 'releaseDate', value: {} }), query);
});

test('params leave out empty values and join statuses', () => {
  assert.deepEqual(
    animeSeasonsParams({ ...query, format: '', statuses: ['untracked', 'Planning'] }),
    { season: 'fall', year: '2026', sort: 'score', direction: 'desc', statuses: 'untracked,Planning' },
  );
});
