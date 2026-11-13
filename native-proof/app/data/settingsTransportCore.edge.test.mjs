import assert from 'node:assert/strict';
import test from 'node:test';
import {
  SettingsSignedOutError,
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
  grantsFromPayload,
  historyFromPayload,
  homeBody,
  homeFromPayload,
  maskToken,
  notificationPatchFromForm,
  notificationsToForm,
  preferencesMeta,
  preferencesPatch,
  preferencesToForm,
  rssFeedUrl,
  rssFromPayload,
  scheduleBody,
  schedulesFromPayload,
  tokensFromPayload,
} from './settingsTransportCore.js';

test('preferencesToForm coerces the numeric fields to strings', () => {
  assert.deepEqual(preferencesToForm(undefined), {});
  assert.deepEqual(
    preferencesToForm({ preferences: { theme: 'dark', session_duration: 30, rating_scale: 10, unknown_field: 1 } }),
    { theme: 'dark', session_duration: '30', rating_scale: '10' },
  );
});

test('preferencesMeta defaults the superuser flag, libraries and choices', () => {
  assert.deepEqual(preferencesMeta(undefined), { isSuperuser: false, autoPauseLibraries: [], choices: {} });
});

test('preferencesPatch drops non-numeric session values and derives the auto-pause flag', () => {
  assert.deepEqual(preferencesPatch(undefined), {});
  assert.deepEqual(
    preferencesPatch({
      theme: 'dark',
      session_duration: 'abc',
      rating_scale: '8',
      auto_pause_in_progress_enabled: true,
      auto_pause_rules: [{}],
    }),
    // auto_pause_rules is itself a preference field, and it flips the flag on.
    { theme: 'dark', rating_scale: '8', auto_pause_rules: [{}], auto_pause_in_progress_enabled: true },
  );
  assert.deepEqual(
    preferencesPatch({ theme: 'dark', auto_pause_rules: [] }),
    { theme: 'dark', auto_pause_rules: [], auto_pause_in_progress_enabled: false },
  );
});

test('notification forms and patches round-trip with only the filled URLs', () => {
  assert.deepEqual(notificationsToForm(undefined), {
    dailyDigestEnabled: false,
    releaseNotificationsEnabled: false,
    premiereNotificationsEnabled: false,
    notificationUrlsConfigured: false,
    playbackWebhookConfigured: false,
  });
  assert.deepEqual(notificationPatchFromForm(undefined), {
    daily_digest_enabled: false,
    release_notifications_enabled: false,
    premiere_notifications_enabled: false,
  });
  assert.deepEqual(
    notificationPatchFromForm({ dailyDigestEnabled: true, playbackWebhookUrl: 'https://x/hook' }),
    {
      daily_digest_enabled: true,
      release_notifications_enabled: false,
      premiere_notifications_enabled: false,
      playback_webhook_url: 'https://x/hook',
    },
  );
});

test('appearance payloads and bodies fall back to the system theme', () => {
  assert.deepEqual(appearanceFromPayload(undefined), {
    presets: {}, colors: {}, effects: {}, families: {},
    values: { theme: 'system', palette: {}, layouts: {} },
  });
  assert.deepEqual(appearanceBody({ theme: 'dark' }), { theme: 'dark', custom_theme: {}, detail_layouts: {} });
});

test('cards and home payloads round-trip and drop the server icon svg', () => {
  assert.deepEqual(cardsFromPayload(undefined), { catalog: [], values: { saved: {}, touchActions: false } });
  assert.deepEqual(
    cardsBody({ saved: { movie: ['poster'] }, touchActions: true }),
    { card_metadata: { types: { movie: ['poster'] } }, clickable_media_cards: true },
  );
  assert.deepEqual(homeFromPayload(undefined).values, {
    sections: [],
    showMediaTypeHeaders: false,
    mediaTypeChipsEnabled: false,
    mediaTypeChipStyle: '',
  });
  const home = homeFromPayload({ sections: [{ key: 'a', icon_svg: '<svg/>' }], show_media_type_headers: 1 });
  assert.deepEqual(home.sections, [{ key: 'a' }]);
  assert.equal(home.values.showMediaTypeHeaders, true);
  assert.deepEqual(
    homeBody({ sections: [{ key: 'a' }], showMediaTypeHeaders: true, mediaTypeChipsEnabled: true }),
    {
      sections: [{ key: 'a' }],
      show_media_type_headers: true,
      media_type_chips_enabled: true,
      media_type_chip_style: undefined,
    },
  );
});

test('schedules map labels and leave undated runs blank', () => {
  assert.deepEqual(schedulesFromPayload(undefined), { mediaTypes: [], schedules: [] });
  const model = schedulesFromPayload({
    media_types: [{ value: 'movie', label: 'Movies' }],
    results: [{ task_name: 't', frequency: 'daily', media_types: ['movie', 'nope'] }],
  });
  assert.equal(model.schedules[0].id, 't');
  assert.equal(model.schedules[0].mediaTypesLabel, 'Movies, nope');
  assert.equal(model.schedules[0].lastRun, '');
  assert.deepEqual(
    scheduleBody({ frequency: 'daily', time: '10:00', selectedMediaTypes: ['movie'], includeLists: true }),
    { frequency: 'daily', time: '10:00', media_types: ['movie'], include_lists: true, include_collection: false },
  );
});

test('exportPath repeats media_types and encodes the flags', () => {
  assert.equal(
    exportPath({ selectedMediaTypes: ['movie', 'tv'], includeLists: true, includeCollection: false }),
    '/api/v1/export/csv/?media_types=movie&media_types=tv&include_lists=1&include_collection=0',
  );
  assert.equal(exportPath({}), '/api/v1/export/csv/?include_lists=0&include_collection=0');
});

test('history and rss payloads default to empty', () => {
  assert.deepEqual(historyFromPayload(undefined), []);
  assert.deepEqual(rssFromPayload(undefined), { mediaTypes: [], template: '' });
  assert.equal(rssFeedUrl('', { mediaType: 'movie', rowKey: 'r' }), '');
  assert.equal(
    rssFeedUrl('https://x/rss/MEDIA_TYPE_PLACEHOLDER/ROW_KEY_PLACEHOLDER.xml', {
      mediaType: 'movie', rowKey: 'r1', skipPlanning: true, skipCollected: false,
    }),
    'https://x/rss/movie/r1.xml?skip_planning=1&skip_collected=0',
  );
});

test('tokens mark expired entries and list preset scopes', () => {
  assert.deepEqual(tokensFromPayload(undefined), { tokens: [], scopes: [], presetScopes: [] });
  const model = tokensFromPayload({
    results: [
      { id: 1, name: 'old', prefix: 'aaa', expires_at: '2000-01-01T00:00:00Z' },
      { id: 2, name: 'live', prefix: 'bbb', expires_at: '2999-01-01T00:00:00Z', scopes: ['catalog:read'] },
      { id: 3, name: 'open', prefix: 'ccc' },
    ],
    scope_choices: [
      { value: 'catalog:read', description: 'd', default: true },
      { value: 'lists:write', description: 'e' },
    ],
  });
  assert.equal(model.tokens[0].expired, true);
  assert.equal(model.tokens[1].expired, false);
  assert.equal(model.tokens[2].expired, false);
  assert.deepEqual(model.presetScopes, ['catalog:read']);
});

test('grants and applications default to empty lists', () => {
  assert.deepEqual(grantsFromPayload(undefined), []);
  assert.deepEqual(applicationsFromPayload(undefined), []);
});

test('maskToken keeps only the last four characters', () => {
  assert.equal(maskToken(''), '');
  assert.equal(maskToken(null), '');
  assert.equal(maskToken('secret-abcd'), `${'\u2022'.repeat(12)}abcd`);
  assert.equal(maskToken('ab'), `${'\u2022'.repeat(12)}ab`);
});

test('advancedFromPayload defaults the cache and port blocks', () => {
  const model = advancedFromPayload(undefined);
  assert.equal(model.isSuperuser, false);
  assert.equal(model.imageCache.enabled, false);
  assert.equal(model.imageCache.count, 0);
  assert.equal(model.imageCache.size, '0 B');
  assert.deepEqual(model.serverPort, { canManage: false });
});

test('absoluteUrl joins the server base and passes absolute urls through', () => {
  assert.equal(absoluteUrl('https://x.com', '/a'), 'https://x.com/a');
  assert.equal(absoluteUrl('', '/a'), '/a');
  assert.equal(absoluteUrl('https://x.com/', 'a'), 'https://x.com/a');
  assert.equal(absoluteUrl('https://x.com', 'http://y.com/z'), 'http://y.com/z');
  assert.equal(absoluteUrl('https://x.com', ''), '');
});

test('aboutFromPayload resolves spec urls against the server', () => {
  assert.equal(aboutFromPayload(undefined).version, '');
  const about = aboutFromPayload({ version: '1', specs: [{ name: 'api', url: '/api/spec.yaml' }] }, 'https://x.com');
  assert.deepEqual(about.specs, [{ name: 'api', path: '/api/spec.yaml', url: 'https://x.com/api/spec.yaml' }]);
});

test('specification preview requests the original server text', async () => {
  const calls = [];
  const transport = createRemoteSettingsActions(async (path, options) => {
    calls.push({ path, options });
    return '{\n  "openapi": "3.0.3"\n}\n';
  });
  assert.equal(await transport.loadSpecification('/api/openapi.yaml'), '{\n  "openapi": "3.0.3"\n}\n');
  assert.deepEqual(calls, [{ path: '/api/openapi.yaml', options: { headers: { Accept: 'text/plain, text/yaml, application/json, application/ld+json, */*' }, responseType: 'text' } }]);
});

test('the signed-out error carries its code and every action rejects with it', async () => {
  const transport = createLocalSettingsActions('Sign in to manage settings.');
  assert.equal(transport.mode, 'local');
  await assert.rejects(
    () => transport.loadPreferences(),
    error => error instanceof SettingsSignedOutError && error.code === 'signed_out',
  );
  await assert.rejects(() => transport.savePreferences({ theme: 'dark' }), SettingsSignedOutError);
  await assert.rejects(() => transport.loadAbout(), SettingsSignedOutError);
});

test('remote actions preserve rating choices as strings and coerce session duration', async () => {
  const calls = [];
  const transport = createRemoteSettingsActions(async (path, options) => {
    calls.push({ path, options });
    return {};
  });
  await transport.savePreferences({ theme: 'dark', session_duration: '3600', rating_scale: '10' });
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(calls[0].options.body, { theme: 'dark', session_duration: 3600, rating_scale: '10' });
});
