import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalTagsActions,
  sortTags,
  tagFromPayload,
  tagsFromPayload,
} from './tagsTransportCore.js';

test('tagFromPayload keeps a zero id and defaults the rest', () => {
  assert.deepEqual(tagFromPayload({ id: 0, name: 'Zero' }), {
    id: 0, name: 'Zero', count: 0, createdAt: '', types: [],
  });
  assert.deepEqual(tagFromPayload({ id: 2 }), {
    id: 2, name: '', count: 0, createdAt: '', types: [],
  });
  assert.equal(tagFromPayload({ name: 'No id' }), null);
  assert.equal(tagFromPayload(undefined), null);
});

test('type breakdown coerces counts and drops rows without a media type', () => {
  const tag = tagFromPayload({
    id: 1,
    name: 'X',
    type_breakdown: [
      { media_type: 'movie', count: '7' },
      { media_type: 'tv', count: null },
      { count: 9 },
      null,
      'nope',
    ],
  });
  assert.deepEqual(tag.types, [
    { key: 'movie', label: 'Movie', count: 7 },
    { key: 'tv', label: 'Tv', count: 0 },
  ]);
  assert.deepEqual(tagFromPayload({ id: 1, type_breakdown: 'nope' }).types, []);
});

test('tagsFromPayload rejects junk payloads at every level', () => {
  assert.deepEqual(tagsFromPayload('nope'), []);
  assert.deepEqual(tagsFromPayload({ results: 'x' }), []);
  assert.deepEqual(tagsFromPayload({ results: [{ name: 'Lost' }, null] }), []);
});

test('sortTags sorts by name or count descending with a name tiebreak', () => {
  assert.deepEqual(sortTags([], 'count'), []);
  const tags = [
    { id: 1, name: 'banana', count: 2 },
    { id: 2, name: 'apple', count: 5 },
    { id: 3, name: 'cherry', count: 5 },
    { id: 4, name: 'Apple', count: 1 },
  ];
  assert.deepEqual(sortTags(tags, 'name').map(tag => tag.name), ['apple', 'Apple', 'banana', 'cherry']);
  assert.deepEqual(sortTags(tags, 'count').map(tag => tag.name), ['apple', 'cherry', 'banana', 'Apple']);
  assert.deepEqual(sortTags(tags).map(tag => tag.name), ['apple', 'Apple', 'banana', 'cherry']);
  assert.deepEqual(sortTags(tags, 'bogus').map(tag => tag.name), ['apple', 'Apple', 'banana', 'cherry']);
  // The input array is not mutated.
  assert.equal(tags[0].name, 'banana');
});

test('the local tags transport answers with the given reason', async () => {
  const transport = createLocalTagsActions('Sign in to your Floppy server to load your tags.');
  assert.equal(transport.mode, 'local');
  assert.deepEqual(await transport.load(), {
    local: true,
    reason: 'Sign in to your Floppy server to load your tags.',
  });
});
