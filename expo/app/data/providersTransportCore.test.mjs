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

function recorder(reply = {}) {
  const calls = [];
  const request = async (path, options) => { calls.push({ path, options }); return reply; };
  return { calls, request };
}

test('directory mapping keeps the shared model and drops malformed items', () => {
  const model = directoryFromPayload({
    items: [{ slug: 'trakt', title: 'Trakt', status: { label: 'Needs setup', tone: 'warning' } }, null, {}],
    filters: { q: 'tr' },
  });
  assert.equal(model.items.length, 1);
  assert.deepEqual(model.filters, { q: 'tr', capability: '', media: '' });
  assert.equal(model.canPin, true);
  assert.deepEqual(directoryFromPayload(null).items, []);
});

test('detail mapping forces native ownership and preserves browser account status', () => {
  const detail = detailFromPayload({
    slug: 'jellyfin',
    page: { tab: 'connection', contentOwner: 'server', labels: { A: 'B' } },
    connection: { mode: 'form', account: { fields: [] }, canSchedule: false },
    guides: [{ title: 'Guide' }],
    guideCopy: { webhook: 'https://x.test/webhook/jellyfin/tok' },
  });
  assert.equal(detail.page.contentOwner, 'react');
  assert.deepEqual(detail.settingsModel.account, { fields: [] });
  assert.equal(detail.settingsModel.setupGuides.length, 1);
  const browser = detailFromPayload({ slug: 'trakt', page: { tab: 'connection' }, connection: { mode: 'browser', account: { fields: [] } } });
  assert.deepEqual(browser.settingsModel.account, { fields: [] });
  assert.deepEqual(detailFromPayload(undefined).schedules, []);
});

test('import body trims the username and defaults to a one-time import', () => {
  assert.deepEqual(importBody({ username: '  neo ' }), { user: 'neo', frequency: 'once' });
  assert.deepEqual(importBody({ username: 'a', mode: 'new', frequency: 'daily', time: '03:00' }), {
    user: 'a', mode: 'new', frequency: 'daily', time: '03:00',
  });
});

test('credentials body omits blank fields so saved values are kept', () => {
  assert.deepEqual(credentialsBody('personal', { api_key: ' k ', secret: '', other: undefined }), {
    scope: 'personal', values: { api_key: 'k' },
  });
  assert.equal(credentialsBody('instance', {}).scope, 'instance');
});

test('remote actions call the provider endpoints', async () => {
  const { calls, request } = recorder();
  const actions = createRemoteProvidersActions(request);
  await actions.directory({ q: 'x', capability: '', media: 'movie' });
  await actions.detail('mal', 'import');
  await actions.pin('mal', true);
  await actions.connect('jellyfin', { base_url: 'u' });
  await actions.disconnect('radarr', { instance_id: 2 });
  await actions.saveCredentials('tmdb', 'personal', { api_key: 'k' });
  await actions.clearCredentials('tmdb');
  await actions.test('jellyfin');
  await actions.sync('radarr', 3);
  await actions.importNow('mal', { username: 'a' });
  await actions.deleteSchedule('mal', 'Import from MAL');
  assert.deepEqual(calls.map(call => `${call.options?.method || 'GET'} ${call.path}`), [
    'GET /api/v1/providers/',
    'GET /api/v1/providers/mal/',
    'POST /api/v1/providers/pin/',
    'POST /api/v1/providers/jellyfin/connect/',
    'POST /api/v1/providers/radarr/disconnect/',
    'PUT /api/v1/providers/tmdb/credentials/',
    'DELETE /api/v1/providers/tmdb/credentials/',
    'POST /api/v1/providers/jellyfin/test/',
    'POST /api/v1/providers/radarr/sync/',
    'POST /api/v1/providers/mal/import/',
    'DELETE /api/v1/providers/mal/schedules/',
  ]);
  assert.deepEqual(calls[0].options.query, { q: 'x', media: 'movie' });
  assert.deepEqual(calls[8].options.body, { instance_id: 3 });
});

test('local actions resolve with the signed-out reason', async () => {
  const actions = createLocalProvidersActions('Sign in');
  assert.equal(actions.mode, 'local');
  assert.deepEqual(await actions.connect('x'), { local: true, reason: 'Sign in' });
});

test('option forms and file imports post to their own routes and details carry them', async () => {
  const { calls, request } = recorder({});
  const actions = createRemoteProvidersActions(request);
  await actions.saveForm('jellyfin', 'jellyfin_events', { jellyfin_mark_played_enabled: true }, 'tracking');
  await actions.importFile('goodreads', { name: 'g.csv', content: 'a', mode: 'new' });
  assert.equal(calls[0].path, '/api/v1/providers/jellyfin/forms/jellyfin_events/');
  assert.deepEqual(calls[0].options.body, { tab: 'tracking', values: { jellyfin_mark_played_enabled: true } });
  assert.equal(calls[1].path, '/api/v1/providers/goodreads/file-import/');
  assert.deepEqual(calls[1].options.body, { name: 'g.csv', content: 'a', mode: 'new' });
  const detail = detailFromPayload({ slug: 'plex', forms: { plex_usernames: { id: 'x' } }, fileImport: { fileField: 'f' } });
  assert.deepEqual(Object.keys(detail.forms), ['plex_usernames']);
  assert.equal(detail.fileImport.fileField, 'f');
  assert.deepEqual(detailFromPayload({}).forms, {});
});


test('provider model preserves protected-guide state without removing configuration', () => {
  const detail = detailFromPayload({
    slug: 'jellyfin', guidesSessionRequired: true, guides: [], guideCopy: {},
    connection: { mode: 'form', account: { fields: [] }, canTest: true },
    forms: { jellyfin_events: { fields: [] } },
  });
  assert.equal(detail.settingsModel.guidesSessionRequired, true);
  assert.deepEqual(detail.settingsModel.guideCopy, {});
  assert.equal(detail.connection.canTest, true);
  assert.ok(detail.forms.jellyfin_events);
});
