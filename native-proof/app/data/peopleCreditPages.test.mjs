import assert from 'node:assert/strict';
import test from 'node:test';
import {
  appendCreditPage,
  creditPageQuery,
  createRemotePeopleActions,
  keepLoadedCredits,
} from './peopleTransportCore.js';

const credit = id => ({ id: `movie:${id}`, title: `Film ${id}` });
const ids = list => list.map(entry => entry.id);

test('creditPageQuery names one grid and its page', () => {
  assert.deepEqual(creditPageQuery(), {});
  assert.deepEqual(creditPageQuery({ section: 'cast', page: 2 }), {});
  assert.deepEqual(creditPageQuery({ section: 'watched' }), {});
  assert.deepEqual(creditPageQuery({ section: 'watched', page: 2 }), { section: 'watched', watched_page: 2 });
  assert.deepEqual(creditPageQuery({ section: 'filmography', page: 3 }), { section: 'filmography', credits_page: 3 });
});

test('loadPerson sends filters and the page together', async () => {
  const calls = [];
  const actions = createRemotePeopleActions((path, options) => {
    calls.push({ path, options });
    return Promise.resolve({ kind: 'person' });
  });
  await actions.loadPerson({ source: 'tmdb', personId: '7', filters: { sort: 'title' }, page: { section: 'filmography', page: 2 } });
  assert.equal(calls[0].path, '/api/v1/people/tmdb/7/');
  assert.deepEqual(calls[0].options.query, { sort: 'title', section: 'filmography', credits_page: 2 });
});

test('appendCreditPage adds the next page below, once, and moves the cursor', () => {
  const current = { kind: 'person', watched: [credit(1)], filmography: [credit(1), credit(2)], filmographyNextPage: 2, filmographyTotal: 4, watchedNextPage: null };
  const next = appendCreditPage(current, { kind: 'person', watched: [], filmography: [credit(2), credit(3), credit(4)], filmographyNextPage: null, filmographyTotal: 4 }, 'filmography');
  assert.deepEqual(ids(next.filmography), ['movie:1', 'movie:2', 'movie:3', 'movie:4']);
  assert.equal(next.filmographyNextPage, null);
  assert.deepEqual(next.watched, current.watched);
  assert.equal(appendCreditPage(null, {}, 'filmography'), null);
  assert.equal(appendCreditPage(current, {}, 'cast'), current);
});

test('keepLoadedCredits keeps scrolled pages under a refreshed first page', () => {
  const current = { kind: 'person', filmography: [credit(1), credit(2), credit(3)], filmographyNextPage: 3, watched: [credit(1)], watchedNextPage: null };
  const fresh = { kind: 'person', talentPending: false, filmography: [{ ...credit(1), watchedRuntimeLabel: '2h' }, credit(2)], filmographyNextPage: 2, watched: [credit(1)], watchedNextPage: null };
  const merged = keepLoadedCredits(current, fresh);
  assert.deepEqual(ids(merged.filmography), ['movie:1', 'movie:2', 'movie:3']);
  assert.equal(merged.filmography[0].watchedRuntimeLabel, '2h');
  assert.equal(merged.filmographyNextPage, 3);
  assert.equal(merged.talentPending, false);
  // Nothing loaded beyond the first page: the fresh answer as it is.
  assert.equal(keepLoadedCredits({ kind: 'person', filmography: [credit(1)] }, fresh).filmography, fresh.filmography);
  assert.equal(keepLoadedCredits(null, fresh), fresh);
});
