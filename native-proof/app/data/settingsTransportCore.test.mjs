import assert from 'node:assert/strict';
import test from 'node:test';
import {
  aboutFromPayload,
  absoluteUrl,
  advancedFromPayload,
  appearanceBody,
  appearanceFromPayload,
  applicationsFromPayload,
  cardsBody,
  cardsFromPayload,
  createLocalSettingsActions,
  createRemoteSettingsActions,
  exportPath,
  homeBody,
  homeFromPayload,
  maskToken,
  notificationPatchFromForm,
  notificationsToForm,
  preferencesMeta,
  preferencesPatch,
  preferencesToForm,
  rssFeedUrl,
  schedulesFromPayload,
  tokensFromPayload,
} from './settingsTransportCore.js';

function recorder(response = {}) {
  const calls = [];
  const request = async (path, options) => {
    calls.push({ path, options });
    return response;
  };
  return { calls, request, actions: createRemoteSettingsActions(request) };
}

test('preferences round trip includes the fields the web form saves', () => {
  const form = preferencesToForm({
    preferences: {
      theme: 'dracula',
      logo_style: 'monochrome',
      ui_language: 'de',
      show_recommendations: false,
      watch_provider_region: 'US',
      metadata_language: 'fr',
      auto_pause_rules: [{ library: 'tv', weeks: 4 }],
      default_edit_entry_date: 'no_date',
      session_duration: 86400,
      rating_scale: '10',
    },
  });
  assert.equal(form.theme, 'dracula');
  assert.equal(form.session_duration, '86400');
  assert.deepEqual(form.auto_pause_rules, [{ library: 'tv', weeks: 4 }]);
  assert.equal(form.default_edit_entry_date, 'no_date');
  const patch = preferencesPatch(form);
  assert.equal(patch.theme, 'dracula');
  assert.equal(patch.show_recommendations, false);
  assert.equal(patch.session_duration, 86400);
  assert.equal(patch.rating_scale, '10');
  assert.equal(patch.auto_pause_in_progress_enabled, true);
  assert.deepEqual(patch.auto_pause_rules, [{ library: 'tv', weeks: 4 }]);
  assert.equal(patch.default_edit_entry_date, 'no_date');
});

test('an empty rule list turns auto-pause off', () => {
  assert.equal(preferencesPatch({ auto_pause_rules: [] }).auto_pause_in_progress_enabled, false);
});

test('preferences meta carries the superuser flag and library list', () => {
  const meta = preferencesMeta({ is_superuser: true, preferences: { auto_pause_libraries: ['tv'] }, choices: { a: [1] } });
  assert.equal(meta.isSuperuser, true);
  assert.deepEqual(meta.autoPauseLibraries, ['tv']);
  assert.equal(preferencesMeta({}).isSuperuser, false);
});

test('notifications keep the premiere toggle and webhook state', () => {
  const form = notificationsToForm({
    daily_digest_enabled: true,
    release_notifications_enabled: false,
    premiere_notifications_enabled: true,
    notification_urls_configured: true,
    playback_webhook_configured: true,
  });
  assert.equal(form.premiereNotificationsEnabled, true);
  assert.equal(form.playbackWebhookConfigured, true);
  const patch = notificationPatchFromForm({ ...form, playbackWebhookUrl: '', playbackWebhookSecret: '' });
  assert.equal(patch.premiere_notifications_enabled, true);
  assert.equal('playback_webhook_url' in patch, false);
  assert.equal('notification_urls' in patch, false);
});

test('appearance payload maps to editor props and back', () => {
  const mapped = appearanceFromPayload({
    theme: 'custom',
    presets: { custom: { label: 'Custom palette' } },
    colors: {},
    effects: {},
    families: {},
    palette: { accent: '#112233' },
    layouts: { media: { content: ['notes'] } },
  });
  assert.equal(mapped.values.theme, 'custom');
  assert.deepEqual(appearanceBody(mapped.values), {
    theme: 'custom',
    custom_theme: { accent: '#112233' },
    detail_layouts: { media: { content: ['notes'] } },
  });
});

test('cards payload maps profiles and wraps them for saving', () => {
  const mapped = cardsFromPayload({ catalog: [{ id: 'movie' }], profiles: { movie: { lines: [] } }, clickable_media_cards: true });
  assert.equal(mapped.values.touchActions, true);
  assert.deepEqual(cardsBody(mapped.values), {
    card_metadata: { types: { movie: { lines: [] } } },
    clickable_media_cards: true,
  });
});

test('home screen payload drops server svg and saves chip settings', () => {
  const mapped = homeFromPayload({
    sections: [{ media_type: 'movie', icon_svg: '<svg/>', rows: [] }],
    show_media_type_headers: true,
    media_type_chips_enabled: true,
    media_type_chip_style: 'soft',
    media_type_chip_styles: [{ value: 'soft', label: 'Soft' }],
  });
  assert.equal('icon_svg' in mapped.sections[0], false);
  const body = homeBody(mapped.values);
  assert.equal(body.show_media_type_headers, true);
  assert.equal(body.media_type_chip_style, 'soft');
});

test('schedules map labels and format empty dates safely', () => {
  const mapped = schedulesFromPayload({
    media_types: [{ value: 'movie', label: 'Movies' }],
    results: [{ task_name: 't1', frequency: 'Weekly', media_types: ['movie', 'x'], include_lists: true, last_run: null, next_run: 'not a date' }],
  });
  assert.equal(mapped.schedules[0].id, 't1');
  assert.equal(mapped.schedules[0].mediaTypesLabel, 'Movies, x');
  assert.equal(mapped.schedules[0].lastRun, '');
  assert.equal(mapped.schedules[0].nextRun, '');
});

test('export path repeats media_types', () => {
  assert.equal(
    exportPath({ selectedMediaTypes: ['movie', 'tv'], includeLists: true, includeCollection: false }),
    '/api/v1/export/csv/?media_types=movie&media_types=tv&include_lists=1&include_collection=0',
  );
});

test('rss url fills the placeholders', () => {
  const url = rssFeedUrl('https://h/rss/tok/MEDIA_TYPE_PLACEHOLDER/ROW_KEY_PLACEHOLDER.xml', {
    mediaType: 'movie', rowKey: 'trending', skipPlanning: true, skipCollected: false,
  });
  assert.equal(url, 'https://h/rss/tok/movie/trending.xml?skip_planning=1&skip_collected=0');
  assert.equal(rssFeedUrl('', { mediaType: 'movie', rowKey: 'x' }), '');
});

test('tokens, grants and applications map without secrets', () => {
  const tokens = tokensFromPayload({
    results: [{ id: 1, name: 'Phone', prefix: 'flp_abc', scopes: ['user:read'], created_at: '2026-01-01T00:00:00Z', expires_at: '2020-01-01T00:00:00Z' }],
    scope_choices: [{ value: 'user:read', description: 'Read', default: true }],
  });
  assert.equal(tokens.tokens[0].expired, true);
  assert.deepEqual(tokens.presetScopes, ['user:read']);
  assert.equal('secret' in tokens.tokens[0], false);
  const apps = applicationsFromPayload({ results: [{ client_id: 'flp_oauth_x', name: 'X', scopes: [{ label: 'L', description: 'D' }] }] });
  assert.equal(apps[0].id, 'flp_oauth_x');
  assert.equal(maskToken('abcdefgh1234').endsWith('1234'), true);
  assert.equal(maskToken(''), '');
});

test('advanced hides superuser controls when the server says so', () => {
  const mapped = advancedFromPayload({ isSuperuser: false });
  assert.equal(mapped.isSuperuser, false);
  assert.equal(mapped.serverPort.canManage, false);
  const admin = advancedFromPayload({ isSuperuser: true, imageEnabled: true, imageCount: 3, imageSize: '1 MB', serverPort: { runtimePort: 8000 } });
  assert.equal(admin.imageCache.count, 3);
  assert.equal(admin.serverPort.runtimePort, 8000);
});

test('about makes spec links absolute against the session server', () => {
  const about = aboutFromPayload({ version: '1.0', specs: [{ label: 'API', url: '/api/docs/' }], releases: [{ tag: 'v1' }] }, 'https://floppy.test/');
  assert.equal(about.specs[0].url, 'https://floppy.test/api/docs/');
  assert.equal(absoluteUrl('https://a', 'https://b/x'), 'https://b/x');
  assert.equal(about.releases.length, 1);
});

test('remote actions use the documented routes and methods', async () => {
  const { calls, actions } = recorder({});
  await actions.saveAppearance({ theme: 'dark', palette: {}, layouts: {} });
  await actions.revokeAppToken({ id: 7 });
  await actions.clearCache('history');
  await actions.saveServerPort(8081);
  await actions.resetServerPort();
  await actions.deleteSchedule({ id: 'job' });
  await actions.updateUser(3, { isActive: false });
  await actions.restoreBackup({ content: 'a,b', mode: 'new' });
  assert.deepEqual(calls.map(call => [call.options?.method, call.path]), [
    ['PUT', '/api/v1/user/appearance/'],
    ['DELETE', '/api/v1/user/tokens/7/'],
    ['DELETE', '/api/v1/user/advanced/caches/history/'],
    ['PUT', '/api/v1/user/advanced/server-port/'],
    ['DELETE', '/api/v1/user/advanced/server-port/'],
    ['DELETE', '/api/v1/exports/schedules/'],
    ['PATCH', '/api/v1/admin/users/3/'],
    ['POST', '/api/v1/user/restore/'],
  ]);
  assert.deepEqual(calls[5].options.body, { task_name: 'job' });
});

test('signed-out actions reject instead of faking success', async () => {
  const actions = createLocalSettingsActions('Sign in first.');
  assert.equal(actions.mode, 'local');
  for (const name of ['loadPreferences', 'savePreferences', 'saveAppearance', 'regenerateAccountToken', 'createUser']) {
    await assert.rejects(() => actions[name]({}), error => error.code === 'signed_out' && error.message === 'Sign in first.');
  }
});

test('data page actions hit the backup status, Letterboxd and import settings routes', async () => {
  const { calls, actions } = recorder({});
  await actions.loadBackupStatus();
  await actions.exportLetterboxd();
  await actions.loadImportSettings();
  await actions.saveImportSettings({ frequency: 'daily', mode: 'overwrite' });
  assert.deepEqual(calls.map(call => call.path), [
    '/api/v1/exports/backup-status/',
    '/api/v1/export/letterboxd/',
    '/api/v1/user/import-settings/',
    '/api/v1/user/import-settings/',
  ]);
  assert.equal(calls[3].options.method, 'PUT');
  assert.deepEqual(calls[3].options.body, { frequency: 'daily', mode: 'overwrite' });
});


test('bearer Access settings preserve listing without fetching the account credential', async () => {
  const fixture = recorder({ results: [] });
  const actions = createRemoteSettingsActions(fixture.request, { authType: 'token' });
  assert.equal(actions.canManageCredentials, false);
  const data = await actions.loadAccess();
  assert.deepEqual(data.account, { token: '' });
  assert.deepEqual(fixture.calls.map(call => call.path), [
    '/api/v1/user/tokens/', '/api/v1/user/oauth-applications/',
  ]);
});

test('password session Access settings load the account credential', async () => {
  const fixture = recorder({ results: [] });
  const actions = createRemoteSettingsActions(fixture.request, { authType: 'session' });
  assert.equal(actions.canManageCredentials, true);
  await actions.loadAccess();
  assert.equal(fixture.calls[0].path, '/api/v1/user/token/');
});
