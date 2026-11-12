import assert from 'node:assert/strict';
import test from 'node:test';
import { formatUserDate, setDatePreferences } from './userDate.js';
import { activityLine, detailRows } from './detailTransportCore.js';

test('system default prints the web format in the server time zone', () => {
  setDatePreferences({ timeZone: 'UTC', dateFormat: 'system_default' });
  assert.equal(formatUserDate('2026-10-10T02:52:11.552637Z'), 'Oct. 10, 2026');
  assert.equal(formatUserDate('2024-08-31'), 'Aug. 31, 2024');
  assert.equal(formatUserDate('2026-03-05T12:00:00Z'), 'March 5, 2026');
});

test('the server zone decides the day, not the device', () => {
  setDatePreferences({ timeZone: 'America/New_York', dateFormat: 'system_default' });
  assert.equal(formatUserDate('2026-10-10T02:52:11Z'), 'Oct. 9, 2026');
  setDatePreferences({ timeZone: 'UTC' });
});

test('every date_format preference matches user_date_format', () => {
  const value = '2026-01-18T12:00:00Z';
  const expected = {
    iso_8601: '2026-01-18',
    month_d_yyyy: 'Jan 18, 2026',
    d_mon_yyyy: '18 Jan 2026',
    m_d_yyyy: '1/18/2026',
    d_m_yyyy: '18/1/2026',
    dd_mm_yyyy: '18.01.2026',
    yyyy_mm_dd: '2026/01/18',
    long_eu: '18 Jan, 2026',
  };
  Object.entries(expected).forEach(([dateFormat, text]) => {
    assert.equal(formatUserDate(value, { timeZone: 'UTC', dateFormat }), text, dateFormat);
  });
  assert.equal(formatUserDate('not a date'), '');
  assert.equal(formatUserDate(''), '');
});

test('details add the runtime from metadata and fold show episodes into it', () => {
  assert.deepEqual(
    detailRows({ details: { release_date: '2024-08-31' } }, { runtime_minutes: 118 }),
    [{ label: 'Release Date', value: 'Aug. 31, 2024' }, { label: 'RUNTIME', value: '1h 58min' }],
  );
  assert.deepEqual(
    detailRows({ media_type: 'tv', details: { seasons: 1, episodes: 6 } }, {}),
    [{ label: 'RUNTIME', value: '6 episodes' }],
  );
});

test('progress types print the web progress subtitle', () => {
  assert.equal(activityLine({ mediaType: 'tv', progress: 4, maxProgress: 6 }), 'Progress: 4/6');
  assert.equal(activityLine({ mediaType: 'season', progress: 4, maxProgress: 6 }), 'Progress: 4');
  assert.equal(activityLine({ mediaType: 'movie', runtime: '1h 58min', plays: 1 }), '1h 58min (Watched once)');
});

test('times print like the web season subtitle', async () => {
  const { formatUserTime, formatUserDateTime } = await import('./userDate.js');
  const zone = { timeZone: 'UTC', dateFormat: 'system_default' };
  assert.equal(formatUserTime('2026-11-05T02:52:11Z', zone), '2:52 a.m.');
  assert.equal(formatUserTime('2026-11-05T18:00:00Z', zone), '6 p.m.');
  assert.equal(formatUserTime('2026-11-05T12:00:00Z', zone), 'noon');
  assert.equal(formatUserTime('2026-11-05T00:00:00Z', zone), 'midnight');
  assert.equal(formatUserDateTime('2026-11-05T02:52:11Z', zone), 'Nov. 5, 2026 2:52 a.m.');
});
