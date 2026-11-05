import assert from 'node:assert/strict';
import test from 'node:test';
import { createCalendarTransport } from './calendarTransport.js';
import { createListTransport } from './listTransport.js';
import { createMusicTransport } from './musicTransport.js';
import {
  configureMediaCardTransport,
  hasMediaCardTransport,
  loadLists,
  resetMediaCardTransport,
} from '../surfaces/mediaCardTransport.js';

function authFixture(handler) {
  const calls = [];
  return {
    calls,
    session: {
      serverUrl: 'https://floppy.example',
      authType: 'token',
      request: async (path, options = {}) => {
        calls.push({ path, options });
        return handler ? handler(path, options) : null;
      },
    },
  };
}

test('list transport uses the authenticated request facade', async () => {
  const { calls, session } = authFixture();
  const transport = createListTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.updateVisibility({ listId: 7, visibility: 'private' });
  assert.equal(calls[0].path, '/api/v1/lists/7/');
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(calls[0].options.json, { visibility: 'private' });
});

test('list transport falls back to local preview without a session', () => {
  const transport = createListTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
});

test('calendar transport queues a server refresh through the session', async () => {
  const { calls, session } = authFixture();
  const transport = createCalendarTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.fetchReleases();
  assert.equal(calls[0].path, '/api/v1/calendar/update/');
  assert.equal(calls[0].options.method, 'POST');

  await transport.read();
  assert.equal(calls[1].path, '/api/v1/calendar/');
});

test('calendar transport keeps its local state without a session', async () => {
  const transport = createCalendarTransport();
  assert.equal(transport.mode, 'local');
  assert.equal((await transport.fetchReleases()).local, true);
});

test('media-card transport routes reads and writes through the session', async () => {
  const { calls, session } = authFixture(path => {
    if (path === '/api/v1/lists/') return { results: [{ id: 1, name: 'Favorites' }] };
    if (path === '/api/v1/media/movie/tmdb/42/lists/') return { results: [{ list_id: 1 }] };
    return null;
  });
  configureMediaCardTransport({ auth: session });
  try {
    assert.equal(hasMediaCardTransport(), true);
    const model = await loadLists({ mediaType: 'movie', source: 'tmdb', mediaId: '42', title: 'Dune' }, 'Dune');
    assert.equal(model.lists.length, 1);
    assert.equal(model.lists[0].hasItem, true);
    assert.equal(calls[0].path, '/api/v1/lists/');
    assert.equal(calls[0].options.query.limit, 200);
    assert.equal(calls[1].path, '/api/v1/media/movie/tmdb/42/lists/');
  } finally {
    resetMediaCardTransport();
  }
  assert.equal(hasMediaCardTransport(), false);
});


test('music transport uses the authenticated request facade', async () => {
  const { calls, session } = authFixture();
  const transport = createMusicTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadArtistRelations({ artistId: 9 });
  assert.equal(calls[0].path, '/api/v1/music/artists/9/relations/');

  await transport.syncArtistMembers({ artistId: 9 });
  assert.equal(calls[1].path, '/api/v1/music/artists/9/sync-members/');
  assert.equal(calls[1].options.method, 'POST');

  await transport.syncAlbumMetadata({ albumId: 4 });
  assert.equal(calls[2].path, '/api/v1/music/albums/4/sync-metadata/');
  assert.equal(calls[2].options.method, 'POST');

  await transport.saveTrackNotes({ trackId: 12, notes: 'Side B' });
  assert.equal(calls[3].path, '/api/v1/music/tracks/12/notes/');
  assert.equal(calls[3].options.method, 'PATCH');
  assert.deepEqual(calls[3].options.json, { notes: 'Side B' });

  await transport.saveEpisodeNotes({ episodeId: 33, notes: 'Replay' });
  assert.equal(calls[4].path, '/api/v1/podcasts/episodes/33/notes/');
  assert.equal(calls[4].options.method, 'PATCH');

  await transport.deleteHistory({ mediaType: 'music', historyId: 88 });
  assert.equal(calls[5].path, '/api/v1/history/music/88/');
  assert.equal(calls[5].options.method, 'DELETE');
});

test('music transport keeps its local preview without a session', () => {
  const transport = createMusicTransport();
  assert.equal(transport.mode, 'local');
  assert.match(transport.reason, /sign in/i);
});

test('people transport reads person and studio profiles through the session', async () => {
  const { calls, session } = authFixture((path) => (
    path.startsWith('/studio/')
      ? { kind: 'studio', studio: { name: 'Northlight Interactive' } }
      : { kind: 'person', person: { name: 'Nora Voss' } }
  ));
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport({ auth: session });
  assert.equal(transport.mode, 'server');

  await transport.loadPerson({ source: 'tmdb', personId: 1001, slug: 'nora-voss' });
  assert.equal(calls[0].path, '/person/tmdb/1001/nora-voss?format=json');

  await transport.loadStudio({ source: 'igdb', studioId: 88, slug: 'northlight' });
  assert.equal(calls[1].path, '/studio/igdb/88/northlight?format=json');
});

test('people transport keeps the local preview without a session', async () => {
  const { createPeopleTransport } = await import('./peopleTransport.js');
  const transport = createPeopleTransport();
  assert.equal(transport.mode, 'local');
  assert.equal((await transport.loadPerson({})).local, true);
});
