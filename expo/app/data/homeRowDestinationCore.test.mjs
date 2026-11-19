import assert from 'node:assert/strict';
import test from 'node:test';
import { libraryParamsForRowUrl } from './homeRowDestinationCore.js';

test('maps a library-query row to Library params with native status values', () => {
  const href = '/medialist/tv?sort=next_episode_air_date&direction=desc&layout=grid&status=In+progress&progress=not_caught_up';
  const result = libraryParamsForRowUrl(href);
  assert.equal(result.mediaType, 'tv');
  const query = new URLSearchParams(result.query);
  assert.deepEqual(query.getAll('status'), ['in_progress']);
  assert.equal(query.get('sort'), 'next_episode_air_date');
  assert.equal(query.get('direction'), 'desc');
  assert.equal(query.get('progress'), 'not_caught_up');
});

test('drops the All status and keeps multiple statuses', () => {
  const all = libraryParamsForRowUrl('/medialist/movie?status=All');
  assert.deepEqual(new URLSearchParams(all.query).getAll('status'), []);
  const many = libraryParamsForRowUrl('/medialist/movie?status=Planning&status=Paused');
  assert.deepEqual(new URLSearchParams(many.query).getAll('status'), ['planning', 'paused']);
});

test('returns null for rows without a media list destination', () => {
  assert.equal(libraryParamsForRowUrl(''), null);
  assert.equal(libraryParamsForRowUrl(undefined), null);
  assert.equal(libraryParamsForRowUrl('/list/abc123?sort=title'), null);
});
