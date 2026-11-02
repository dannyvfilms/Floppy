// Self-check for the Statistics media-type merge helpers. This project has no
// browser-JS test runner, so keep this as a plain assert script:
// `node src/static/js/stats-media-merge.selfcheck.mjs`.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
new Function(fs.readFileSync(path.join(dir, 'stats-media-merge.js'), 'utf8'))();
const M = globalThis.StatsMediaMerge;

// Days are epoch-day numbers; 2024-01-01 is day 19723 (a Monday).
const D = 19723;

// --- URL parameter -----------------------------------------------------------
const valid = ['all', 'tv', 'movie', 'anime', 'game'];
assert.deepEqual(M.parseMediaTypeParam('movie,tv', valid), ['tv', 'movie'], 'dropdown order');
assert.deepEqual(M.parseMediaTypeParam('tv', valid), ['tv'], 'old single-type links still work');
assert.deepEqual(M.parseMediaTypeParam('all', valid), []);
assert.deepEqual(M.parseMediaTypeParam(null, valid), []);
assert.deepEqual(M.parseMediaTypeParam('tv,bogus,tv', valid), ['tv']);
assert.equal(M.formatMediaTypeParam(['tv', 'movie']), 'tv,movie');

// --- Summary cards -----------------------------------------------------------
const byType = {
  all: { total: 99, marker: 'all' },
  tv: {
    completed: 2, total: 5, total_minutes: 300, score_sum: 16, score_count: 2,
    // Weekday minutes, Monday first: Monday 200, Tuesday 100.
    weekday_minutes: [200, 100, 0, 0, 0, 0, 0],
    // Jan 1-3 and Jan 10.
    active_runs: [[D, 3], [D + 9, 1]],
    streak_end_day: D + 9,
  },
  movie: {
    completed: 1, total: 2, total_minutes: 120, score_sum: 9, score_count: 1,
    weekday_minutes: [0, 0, 0, 0, 0, 120, 0],
    // Jan 4-5 joins tv's Jan 1-3 into one five-day run; Jan 6 is a Saturday.
    active_runs: [[D + 3, 2]],
    streak_end_day: D + 9,
  },
  game: {
    completed: 0, total: 1, total_minutes: 60, score_sum: 0, score_count: 0,
    weekday_minutes: [0, 0, 0, 0, 0, 0, 60],
    active_runs: [[D + 9, 1]],
    streak_end_day: D + 9,
  },
};

assert.equal(M.mergeSummary(byType, []).marker, 'all', 'nothing selected = server "all" numbers');
assert.equal(M.mergeSummary(byType, ['tv']), byType.tv, 'one type = server numbers untouched');

const tvMovie = M.mergeSummary(byType, ['tv', 'movie']);
assert.equal(tvMovie.completed, 3);
assert.equal(tvMovie.total, 7);
assert.equal(tvMovie.total_minutes, 420);
// Weighted by number of rated items: (16 + 9) / 3, not the mean of 8 and 9.
assert.equal(tvMovie.average_score, 8.33);
assert.equal(tvMovie.has_score, true);
assert.equal(tvMovie.most_active_day, 'Monday');
assert.equal(tvMovie.most_active_day_percentage, Math.round((200 / 420) * 100));
assert.equal(tvMovie.longest_streak, 5, 'tv Jan 1-3 + movie Jan 4-5 are one streak');
assert.equal(tvMovie.longest_streak_start, '2024-01-01');
assert.equal(tvMovie.longest_streak_end, '2024-01-05');
assert.equal(tvMovie.current_streak, 1, 'only Jan 10 reaches the end day');

const withGame = M.mergeSummary(byType, ['tv', 'movie', 'game']);
assert.equal(withGame.current_streak, 1);
assert.equal(withGame.average_score, 8.33, 'unrated types do not dilute the average');

const noScores = M.mergeSummary(byType, ['game', 'game']);
assert.equal(noScores.has_score, false);

// A tie for the longest streak goes to the later one (matches the server).
const tie = M.mergeSummary({
  a: { active_runs: [[D, 2]], streak_end_day: D + 20 },
  b: { active_runs: [[D + 10, 2]], streak_end_day: D + 20 },
}, ['a', 'b']);
assert.equal(tie.longest_streak, 2);
assert.equal(tie.longest_streak_start, '2024-01-11');

// A range with no end day (streak_end_day null) has no current streak.
const noEnd = M.mergeSummary({
  a: { active_runs: [[D, 2]], streak_end_day: null },
  b: { active_runs: [[D + 5, 1]], streak_end_day: null },
}, ['a', 'b']);
assert.equal(noEnd.current_streak, 0);
assert.equal(noEnd.longest_streak, 2);

// Types with no activity are skipped instead of breaking the merge.
assert.equal(M.mergeSummary(byType, ['tv', 'music']).total, 5);
assert.deepEqual(M.mergeSummary(byType, ['music', 'book']), {});

// --- Per year / month / day tiles --------------------------------------------
const metric = (unit, n, extra = {}) => ({
  unit, icon: 'clock', total: n, per_year: n, per_month: n / 12, per_day: n / 365, ...extra,
});
const consumption = {
  all: { has_data: true, marker: 'all' },
  tv: { has_data: true, primary: metric('Hours', 120), secondary: metric('Episodes', 60), bonuses: [] },
  movie: { has_data: true, primary: metric('Hours', 60), secondary: metric('Movies', 30), bonuses: [] },
  anime: { has_data: true, primary: metric('Hours', 24), secondary: metric('Episodes', 12), bonuses: [] },
  book: { has_data: true, primary: metric('Pages', 900), secondary: null, bonuses: [{ kind: 'length' }] },
  music: { has_data: false, primary: null },
};
assert.equal(M.mergeConsumption(consumption, []).marker, 'all');
const hours = M.mergeConsumption(consumption, ['tv', 'movie']);
assert.equal(hours.primary.per_year, 180);
assert.equal(hours.secondary, null, 'Episodes + Movies are different units, so no caption');
assert.deepEqual(hours.bonuses, []);
const episodes = M.mergeConsumption(consumption, ['tv', 'anime']);
assert.equal(episodes.secondary.per_year, 72, 'same secondary unit is summed');
assert.deepEqual(M.mergeConsumption(consumption, ['movie', 'book']), {}, 'hours + pages is not a sum');
assert.equal(M.mergeConsumption(consumption, ['tv', 'music']).primary.per_year, 120, 'no-data types are skipped');

// --- Activity rhythm ---------------------------------------------------------
const grid = (value) => Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => value));
const rhythm = { all: grid(9), tv: grid(1), movie: grid(2) };
assert.equal(M.sumMatrices(rhythm, []), rhythm.all);
assert.equal(M.sumMatrices(rhythm, ['tv', 'movie'])[3][7], 3);
assert.equal(M.sumMatrices(rhythm, ['tv', 'game'])[0][0], 1);
assert.equal(M.sumMatrices(rhythm, ['game']), null);

// --- Hours by month / weekday / time of day ----------------------------------
const bars = (color, data) => ({ labels: ['a', 'b'], datasets: [{ label: 'Hours', data, background_color: color }] });
const series = {
  all: bars('#6366f1', [9, 9]),
  tv: bars('#10b981', [1.5, 0]),
  movie: bars('#f97316', [0.25, 2]),
  game: { labels: [], datasets: [] },
};
assert.equal(M.mergeSeriesChart(series, []), series.all);
assert.equal(M.mergeSeriesChart(series, ['tv']), series.tv);
const merged = M.mergeSeriesChart(series, ['tv', 'movie']);
assert.deepEqual(merged.datasets[0].data, [1.75, 2]);
assert.equal(merged.datasets[0].background_color, '#6366f1', 'combined bars use the "all" colour');
assert.deepEqual(series.tv.datasets[0].data, [1.5, 0], 'inputs are not modified');
assert.equal(M.mergeSeriesChart(series, ['game']), null, 'types without hours give no chart');

console.log('stats-media-merge selfcheck passed');
