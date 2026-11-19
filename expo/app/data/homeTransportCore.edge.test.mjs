import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalHomeActions,
  createRemoteHomeActions,
  homeQuery,
  homeScreenFromPayload,
  mergeHomeRowPage,
} from './homeTransportCore.js';

test('homeQuery defaults to live presentation with deferred rows', () => {
  assert.deepEqual(homeQuery(), { presentation: 1, deferred: 1 });
  assert.deepEqual(homeQuery({ deferred: false }), { presentation: 1, deferred: 0 });
  assert.deepEqual(homeQuery({ deferred: true, limit: 12 }), { presentation: 1, deferred: 1, limit: 12 });
  assert.deepEqual(homeQuery({ limit: undefined }), { presentation: 1, deferred: 1 });
});

test('homeScreenFromPayload defaults every field for an empty payload', () => {
  assert.deepEqual(homeScreenFromPayload(undefined), {
    groups: [],
    deferredGroups: [],
    showMediaTypeHeaders: false,
    readOnly: false,
    labels: {},
  });
  const screen = homeScreenFromPayload({
    groups: [{ key: 'a' }],
    showMediaTypeHeaders: 1,
    readOnly: 'yes',
    labels: { x: 1 },
  });
  assert.equal(screen.groups.length, 1);
  assert.equal(screen.showMediaTypeHeaders, true);
  assert.equal(screen.readOnly, true);
});

test('mergeHomeRowPage returns the row untouched without a page', () => {
  const row = { items: ['a'], total: 1 };
  assert.equal(mergeHomeRowPage(row, undefined), row);
  assert.equal(mergeHomeRowPage(row, null), row);
});

test('mergeHomeRowPage appends items and prefers the page values when present', () => {
  const merged = mergeHomeRowPage(
    { items: ['a'], total: 9, seed: 's', pollForCovers: false },
    { items: ['b'], loadedCount: 5, total: 20, seed: 's2', pollForCovers: true, title: 'T' },
  );
  assert.deepEqual(merged.items, ['a', 'b']);
  assert.equal(merged.loadedCount, 5);
  assert.equal(merged.total, 20);
  assert.equal(merged.seed, 's2');
  assert.equal(merged.pollForCovers, true);
  assert.equal(merged.title, 'T');
});

test('mergeHomeRowPage computes the loaded count and keeps the row totals otherwise', () => {
  const merged = mergeHomeRowPage(
    { items: ['a'], total: 9, seed: 's' },
    { items: ['b'] },
  );
  assert.deepEqual(merged.items, ['a', 'b']);
  assert.equal(merged.loadedCount, 2);
  assert.equal(merged.total, 9);
  assert.equal(merged.seed, 's');
  assert.equal(merged.pollForCovers, false);
  const emptyRow = mergeHomeRowPage({ total: 3 }, { items: ['x'] });
  assert.deepEqual(emptyRow.items, ['x']);
  assert.equal(emptyRow.loadedCount, 1);
});

test('remote home load mirrors the homeQuery contract', async () => {
  const calls = [];
  const transport = createRemoteHomeActions(async (path, options) => {
    calls.push({ path, options });
    return {};
  });
  await transport.load();
  assert.deepEqual(calls[0], { path: '/api/v1/home/', options: { query: { presentation: 1, deferred: 1 } } });
  await transport.load({ deferred: false, limit: 3 });
  assert.deepEqual(calls[1].options.query, { presentation: 1, deferred: 0, limit: 3 });
});

test('loadRow encodes the row id and only sends the seed when set', async () => {
  const calls = [];
  const transport = createRemoteHomeActions(async (path) => {
    calls.push(path);
    return {};
  });
  assert.equal(await transport.loadRow({ rowId: 'a/b' }), null);
  await transport.loadRow({ rowId: 'r1', seed: 'x', limit: 5 });
  await transport.loadRow({ rowId: 'r1', offset: 40, seed: 0 });
  assert.equal(calls[0], '/api/v1/home/row/a%2Fb/');
  assert.deepEqual(calls[1], '/api/v1/home/row/r1/');
});

test('loadRow passes offset, seed and limit in the query', async () => {
  const queries = [];
  const transport = createRemoteHomeActions(async (path, options) => {
    queries.push(options.query);
    return { row: { items: [1] } };
  });
  const row = await transport.loadRow({ rowId: 'r1', seed: 'x', limit: 5 });
  assert.deepEqual(row, { items: [1] });
  await transport.loadRow({ rowId: 'r1', offset: 40, seed: 0 });
  assert.deepEqual(queries[0], { offset: 0, seed: 'x', limit: 5 });
  assert.deepEqual(queries[1], { offset: 40, seed: 0 });
});

test('sortRow posts with the default and custom limits', async () => {
  const calls = [];
  const transport = createRemoteHomeActions(async (path, options) => {
    calls.push({ path, options });
    return { row: {} };
  });
  await transport.sortRow({ rowId: 'r1' });
  await transport.sortRow({ rowId: 'r1', limit: 5 });
  assert.equal(calls[0].path, '/api/v1/home/row/r1/sort/');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(calls[0].options.query, { limit: 14 });
  assert.deepEqual(calls[0].options.body, {});
  assert.deepEqual(calls[1].options.query, { limit: 5 });
});

test('refreshCovers joins the ids and flags pending work', async () => {
  const calls = [];
  const transport = createRemoteHomeActions(async (path, options) => {
    calls.push(options.query);
    return {};
  });
  await transport.refreshCovers();
  await transport.refreshCovers({ ids: ['a', 'b'], pending: 2 });
  assert.deepEqual(calls[0], { ids: '', pending: 0 });
  assert.deepEqual(calls[1], { ids: 'a,b', pending: 1 });
});

test('the local home transport answers every action with the sign-in reason', async () => {
  const transport = createLocalHomeActions('Sign in to your Floppy server to load your home screen.');
  assert.equal(transport.mode, 'local');
  const local = { local: true, reason: 'Sign in to your Floppy server to load your home screen.' };
  assert.deepEqual(await transport.load(), local);
  assert.deepEqual(await transport.loadRow(), local);
  assert.deepEqual(await transport.sortRow(), local);
  assert.deepEqual(await transport.refreshCovers(), local);
});
