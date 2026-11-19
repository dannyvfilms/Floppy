import assert from 'node:assert/strict';
import test from 'node:test';
import { createLocalPeopleActions, createRemotePeopleActions, profileQuery } from './peopleTransportCore.js';

test('profileQuery sends only the filters the person actually chose', () => {
  assert.deepEqual(profileQuery(), {});
  assert.deepEqual(profileQuery({ department: 'all' }), {});
  const query = profileQuery({
    department: 'directing',
    year: 2020,
    genre: 'all',
    implied_genre: 'heist',
    source: null,
    rating: '',
    collection: 'collected',
    sort: 'title',
    direction: 'asc',
  });
  assert.deepEqual(query, {
    department: 'directing',
    year: 2020,
    implied_genre: 'heist',
    collection: 'collected',
    sort: 'title',
    direction: 'asc',
  });
});

test('loadPerson encodes the source and id and expects an object back', async () => {
  const calls = [];
  const transport = createRemotePeopleActions(async (path, options) => {
    calls.push({ path, options });
    return { name: 'Person' };
  });
  const data = await transport.loadPerson({ source: 'tmdb', personId: 'a/b', filters: { sort: 'title' } });
  assert.equal(data.name, 'Person');
  assert.equal(calls[0].path, '/api/v1/people/tmdb/a%2Fb/');
  assert.deepEqual(calls[0].options, { query: { sort: 'title' } });
});

test('a non-object profile payload fails with the shared error copy', async () => {
  const transport = createRemotePeopleActions(async () => '<html>200</html>');
  await assert.rejects(
    () => transport.loadPerson({ source: 'tmdb', personId: '5' }),
    /The profile did not return the expected data/,
  );
  await assert.rejects(
    () => transport.loadStudio({ source: 'tmdb', studioId: '5' }),
    /The profile did not return the expected data/,
  );
});

test('loadStudio addresses the studios route without filters', async () => {
  const calls = [];
  const transport = createRemotePeopleActions(async (path) => {
    calls.push(path);
    return { name: 'Studio' };
  });
  await transport.loadStudio({ source: 'tmdb', studioId: 'x y' });
  assert.equal(calls[0], '/api/v1/studios/tmdb/x%20y/');
});

test('the local people transport rejects every load with the reason', async () => {
  const transport = createLocalPeopleActions('Sign in to your Floppy server to load profiles.');
  assert.equal(transport.mode, 'local');
  await assert.rejects(
    () => transport.loadPerson({}),
    /Sign in to your Floppy server to load profiles\./,
  );
  await assert.rejects(() => transport.loadStudio({}), Error);
});
