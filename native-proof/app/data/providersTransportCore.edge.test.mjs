import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createLocalProvidersActions,
  createRemoteProvidersActions,
  credentialsBody,
  detailFromPayload,
  directoryFromPayload,
  importBody,
} from './providersTransportCore.js';

test('directoryFromPayload defaults the filters and keeps pinned state open', () => {
  assert.deepEqual(directoryFromPayload(null), {
    filters: { q: '', capability: '', media: '' },
    capabilities: [],
    media: [],
    items: [],
    canPin: true,
  });
  const model = directoryFromPayload({
    title: 'Providers',
    filters: { q: 'a' },
    items: [{ slug: 'a' }, {}, null],
    canPin: false,
  });
  assert.equal(model.title, 'Providers');
  assert.deepEqual(model.filters, { q: 'a', capability: '', media: '' });
  assert.deepEqual(model.items, [{ slug: 'a' }]);
  assert.equal(model.canPin, false);
});

test('detailFromPayload works without a payload and keeps react as the content owner', () => {
  const detail = detailFromPayload(null);
  assert.equal(detail.slug, '');
  assert.deepEqual(detail.page, { contentOwner: 'react' });
  assert.equal(detail.canImport, false);
  assert.deepEqual(detail.settingsModel, {
    tab: undefined,
    labels: undefined,
    credentials: undefined,
    account: undefined,
    setupGuides: [],
    guideCopy: {},
    guidesSessionRequired: false,
  });
  assert.deepEqual(detail.state, {});
  assert.deepEqual(detail.forms, {});
  assert.equal(detail.fileImport, null);
  assert.equal(detail.importPreferences, null);
});

test('detailFromPayload exposes saved account status for form and browser connections', () => {
  const form = detailFromPayload({
    slug: 'trakt',
    page: { tab: 'main', labels: { a: 'b' } },
    connection: { mode: 'form', account: { user: 'u' }, canSchedule: true },
    credentials: { a: 1 },
  });
  assert.equal(form.slug, 'trakt');
  assert.equal(form.canImport, true);
  assert.equal(form.settingsModel.account.user, 'u');
  assert.deepEqual(form.settingsModel.credentials, { a: 1 });
  const oauth = detailFromPayload({ connection: { mode: 'browser', account: { user: 'u' } } });
  assert.deepEqual(oauth.settingsModel.account, { user: 'u' });
  assert.equal(oauth.canImport, false);
});

test('importBody trims the username and defaults the frequency', () => {
  assert.deepEqual(importBody({}), { user: '', frequency: 'once' });
  assert.deepEqual(
    importBody({ username: ' a ', mode: 'fast', frequency: 'weekly', time: '10:00' }),
    { user: 'a', mode: 'fast', frequency: 'weekly', time: '10:00' },
  );
});

test('credentialsBody scopes personal versus instance and drops blank values', () => {
  assert.deepEqual(credentialsBody('personal', { a: ' x ', b: '   ', c: 5 }), {
    scope: 'personal',
    values: { a: 'x' },
  });
  assert.deepEqual(credentialsBody('other', null), { scope: 'instance', values: {} });
  assert.deepEqual(credentialsBody(undefined, {}), { scope: 'instance', values: {} });
});

test('the local providers transport answers every action with the sign-in reason', async () => {
  const transport = createLocalProvidersActions('Sign in to manage providers.');
  assert.equal(transport.mode, 'local');
  assert.deepEqual(await transport.directory(), { local: true, reason: 'Sign in to manage providers.' });
  assert.deepEqual(await transport.pin('trakt', true), { local: true, reason: 'Sign in to manage providers.' });
});

test('link actions call the connect start, poll and cancel endpoints', async () => {
  const calls = [];
  const actions = createRemoteProvidersActions(async (path, options) => { calls.push({ path, options }); return {}; });
  await actions.startLink('trakt', { returnTo: 'floppy-native-proof://connect/trakt' });
  await actions.pollLink('trakt');
  await actions.cancelLink('trakt');
  assert.deepEqual(calls.map(call => call.path), [
    '/api/v1/providers/trakt/connect/start/',
    '/api/v1/providers/trakt/connect/poll/',
    '/api/v1/providers/trakt/connect/cancel/',
  ]);
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.returnTo, 'floppy-native-proof://connect/trakt');
  assert.equal(calls[1].options?.method, undefined);
});
