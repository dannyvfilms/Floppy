import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalSearchActions,
  resultsQuery,
  searchBarFromPayload,
  suggestionsFromPayload,
} from './searchTransportCore.js';

test('suggestionsFromPayload maps rows and defaults every optional field', () => {
  assert.deepEqual(suggestionsFromPayload(undefined), []);
  assert.deepEqual(suggestionsFromPayload('nope'), []);
  assert.deepEqual(suggestionsFromPayload({ suggestions: [{ title: 'T' }] }), [
    { id: '0', title: 'T', subtitle: '', image: null, mediaType: '', identity: null, href: '', url: '' },
  ]);
  assert.deepEqual(
    suggestionsFromPayload({ suggestions: [{ id: 7, title: 'T', subtitle: 'S', image: 'i.png', url: '/details/tmdb/movie/5' }] }),
    [{ id: '7', title: 'T', subtitle: 'S', image: 'i.png', mediaType: '', identity: null, href: '/details/tmdb/movie/5', url: '/details/tmdb/movie/5' }],
  );
});

// SUSPECTED BUG (searchTransportCore.js:8-11): a null entry inside
// payload.suggestions crashes suggestionsFromPayload with
// "TypeError: Cannot read properties of null (reading 'id')" because the
// mapper guards the list (Array.isArray) but not its rows — unlike
// tagsFromPayload or collectionEntriesFromPayload, which filter null rows.
// Triggering input: suggestionsFromPayload({ suggestions: [null] })
test('a malformed null suggestion row is skipped instead of crashing the search bar', () => {
  assert.deepEqual(
    suggestionsFromPayload({ suggestions: [null, { id: 7, title: 'T' }] }),
    [{ id: '7', title: 'T', subtitle: '', image: null, mediaType: '', identity: null, href: '', url: '' }],
  );
});

test('searchBarFromPayload defaults every block', () => {
  assert.deepEqual(searchBarFromPayload(undefined), {
    mediaTypes: [],
    barcodeTypes: [],
    labels: {},
    sources: [],
    defaultSource: '',
  });
  const bar = searchBarFromPayload({
    media_types: ['movie'],
    barcode_types: ['upc'],
    labels: { q: 'Search' },
    sources: [{ value: 'tmdb' }],
    default_source: 'tmdb',
  });
  assert.deepEqual(bar.mediaTypes, ['movie']);
  assert.deepEqual(bar.labels, { q: 'Search' });
  assert.equal(bar.defaultSource, 'tmdb');
});

test('resultsQuery omits the page on and below the first page', () => {
  assert.deepEqual(resultsQuery(), { q: '', media_type: 'all' });
  assert.deepEqual(resultsQuery({ query: 'x', page: 1 }), { q: 'x', media_type: 'all' });
  assert.deepEqual(
    resultsQuery({ query: 'x', page: 2, source: 'tmdb', layout: 'grid' }),
    { q: 'x', media_type: 'all', source: 'tmdb', page: 2, layout: 'grid' },
  );
  assert.deepEqual(resultsQuery({ mediaType: 'banana' }), { q: '', media_type: 'banana' });
});

test('the local search transport rejects every load with the reason', async () => {
  const transport = createLocalSearchActions('Sign in to search your server.');
  assert.equal(transport.mode, 'local');
  await assert.rejects(() => transport.loadSources({}), /Sign in to search your server\./);
  await assert.rejects(() => transport.loadResults({}), Error);
  await assert.rejects(() => transport.createMusic({}), Error);
});
