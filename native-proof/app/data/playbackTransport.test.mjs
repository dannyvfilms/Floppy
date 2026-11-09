import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createPlaybackTransport,
  playbackCardFromPayload,
  playbackCardsFromPayload,
} from './playbackTransport.js';

const cardPayload = (overrides = {}) => ({
  id: 'plex-movie-701',
  source: 'plex',
  media_type: 'movie',
  media_id: '701',
  title: 'The Quiet Orbit',
  episode_title: 'The Quiet Orbit',
  image: 'https://example.test/poster.jpg',
  status: 'playing',
  progress_percent: 42,
  offset_seconds: 120,
  duration_seconds: 1800,
  updated_at: '2026-11-07T10:00:00Z',
  actions: ['pause', 'finish'],
  ...overrides,
});

test('maps all server cards into shared presentation models without tokens', () => {
  const cards = playbackCardsFromPayload({ cards: [
    cardPayload(),
    cardPayload({ id: 'plex-episode-702', media_type: 'episode', media_id: '702' }),
  ] });
  assert.equal(cards.length, 2);
  assert.equal(cards[0].source, 'plex');
  assert.equal(cards[0].mediaId, '701');
  assert.equal(cards[0].checkin, true);
  assert.equal('token' in cards[0], false);
  assert.equal('checkin_token' in cards[0], false);
});

test('ignores cards without a title and inactive legacy payloads', () => {
  assert.equal(playbackCardFromPayload({ active: false }), null);
  assert.deepEqual(playbackCardsFromPayload({ cards: [cardPayload({ title: '' })] }), []);
});

test('loads the multi-card endpoint and posts only card identity plus action', async () => {
  const calls = [];
  const auth = {
    request: async (path, options) => {
      calls.push({ path, options });
      if (!options) return { cards: [cardPayload()] };
      return undefined;
    },
  };
  const transport = createPlaybackTransport({ auth });
  assert.equal((await transport.load()).length, 1);
  await transport.act((await transport.load())[0], 'finish');
  assert.equal(calls.at(-1).path, '/api/v1/playback/home-cards/');
  assert.deepEqual(calls.at(-1).options.json, {
    source: 'plex',
    media_type: 'movie',
    media_id: '701',
    action: 'finish',
  });
});

test('falls back to the legacy read-only endpoint when the server lacks Home cards', async () => {
  const paths = [];
  const auth = {
    request: async path => {
      paths.push(path);
      if (path.endsWith('/home-cards/')) throw Object.assign(new Error('Not found'), { status: 404 });
      return { ...cardPayload(), active: true, actions: undefined };
    },
  };
  const cards = await createPlaybackTransport({ auth }).load();
  assert.deepEqual(paths, [
    '/api/v1/playback/home-cards/',
    '/api/v1/playback/now-playing/',
  ]);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].checkin, false);
});
