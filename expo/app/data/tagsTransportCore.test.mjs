import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalTagsActions,
  createRemoteTagsActions,
  sortTags,
  tagFromPayload,
  tagsFromPayload,
} from './tagsTransportCore.js';

const tagPayload = (overrides = {}) => ({
  id: 3,
  name: 'Sci-fi',
  created_at: '2026-01-02T03:04:05Z',
  item_count: 27,
  ...overrides,
});

test('maps the fork tags list payload into shared index records', () => {
  const tags = tagsFromPayload({
    results: [
      tagPayload(),
      tagPayload({ id: 4, name: 'Comfort watches', item_count: 11 }),
      tagPayload({ id: 5, item_count: 0 }),
    ],
  });
  assert.equal(tags.length, 3);
  assert.deepEqual(tags[0], {
    id: 3,
    name: 'Sci-fi',
    count: 27,
    createdAt: '2026-01-02T03:04:05Z',
    types: [],
  });
  assert.equal(tags[2].count, 0);
  assert.equal('created_at' in tags[0], false);
});

test('accepts bare arrays and drops malformed entries', () => {
  assert.deepEqual(
    tagsFromPayload([tagPayload({ id: 9 }), { name: 'Lost' }, null]),
    [{ id: 9, name: 'Sci-fi', count: 27, createdAt: '2026-01-02T03:04:05Z', types: [] }],
  );
  assert.deepEqual(tagsFromPayload(undefined), []);
  assert.deepEqual(tagsFromPayload({}), []);
  assert.deepEqual(tagFromPayload({ name: 'No id' }), null);
});

test('coerces missing or string item counts to a finite count', () => {
  assert.equal(tagFromPayload(tagPayload({ item_count: '7' })).count, 7);
  assert.equal(tagFromPayload(tagPayload({ item_count: undefined })).count, 0);
  assert.equal(tagFromPayload(tagPayload({ item_count: null })).count, 0);
});

test('sorts by name, or by count descending with a name tiebreak', () => {
  const tags = tagsFromPayload({
    results: [
      tagPayload({ id: 1, name: 'banana', item_count: 2 }),
      tagPayload({ id: 2, name: 'apple', item_count: 5 }),
      tagPayload({ id: 3, name: 'cherry', item_count: 5 }),
    ],
  });
  assert.deepEqual(sortTags(tags, 'name').map(tag => tag.name), ['apple', 'banana', 'cherry']);
  assert.deepEqual(sortTags(tags, 'count').map(tag => tag.name), ['apple', 'cherry', 'banana']);
  assert.deepEqual(sortTags(tags).map(tag => tag.name), ['apple', 'banana', 'cherry']);
  assert.equal(tags[0].name, 'banana');
});

test('remote transport loads the tags endpoint and deletes by id', async () => {
  const calls = [];
  const transport = createRemoteTagsActions(async (path, options) => {
    calls.push({ path, options });
    if (!options || !options.method) return { results: [tagPayload()] };
    return undefined;
  });
  assert.equal(transport.mode, 'server');
  const payload = await transport.load();
  assert.deepEqual(calls[0], { path: '/api/v1/tags/', options: undefined });
  assert.equal(payload.results.length, 1);
  await transport.remove({ tagId: 12 });
  assert.equal(calls[1].path, '/api/v1/tags/12/');
  assert.equal(calls[1].options.method, 'DELETE');
  await transport.remove({ tagId: 'a/b' });
  assert.equal(calls[2].path, '/api/v1/tags/a%2Fb/');
});

test('local transport reports the sign-in reason without network calls', async () => {
  const transport = createLocalTagsActions('Sign in to your Floppy server to load your tags.');
  assert.equal(transport.mode, 'local');
  assert.deepEqual(await transport.load(), {
    local: true,
    reason: 'Sign in to your Floppy server to load your tags.',
  });
  assert.deepEqual(await transport.remove({ tagId: 1 }), {
    local: true,
    reason: 'Sign in to your Floppy server to load your tags.',
  });
});

test('maps the per-media-type breakdown into chip records', () => {
  const [tag] = tagsFromPayload({
    results: [tagPayload({
      type_breakdown: [
        { media_type: 'movie', count: 3 },
        { media_type: 'tv', count: 1 },
        { count: 9 },
      ],
    })],
  });
  assert.deepEqual(tag.types, [
    { key: 'movie', label: 'Movie', count: 3 },
    { key: 'tv', label: 'Tv', count: 1 },
  ]);
});
