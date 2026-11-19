// Settings transport: every settings page reads and writes through /api/v1/...
// endpoints that work for both session-cookie and Bearer-token sign-in. When
// nobody is signed in every action rejects with a signed-out error; nothing
// pretends to succeed.
const PREFERENCE_FIELDS = [
  'date_format',
  'time_format',
  'currency',
  'week_start_day',
  'activity_history_view',
  'duration_format',
  'game_logging_style',
  'mobile_grid_layout',
  'media_card_subtitle_display',
  'title_display_preference',
  'top_talent_sort_by',
  'rating_scale',
  'show_planned_on_home',
  'anime_library_mode',
  'quick_season_update_mobile',
  'session_duration',
  'hide_completed_recommendations',
  'hide_zero_rating',
  'progress_bar',
  'book_comic_manga_progress_percentage',
  'auto_pause_in_progress_enabled',
  'obfuscate_episodes',
  'clickable_media_cards',
  'home_show_media_type_headers',
  'theme',
  'logo_style',
  'ui_language',
  'show_recommendations',
  'watch_provider_region',
  'metadata_language',
  'auto_pause_rules',
];

export function preferencesToForm(payload) {
  const prefs = payload?.preferences || {};
  const values = {};
  PREFERENCE_FIELDS.forEach(field => {
    if (!(field in prefs)) return;
    if (field === 'session_duration' || field === 'rating_scale') {
      values[field] = String(prefs[field]);
      return;
    }
    values[field] = prefs[field];
  });
  return values;
}

// Server-provided lists the form needs besides its own values.
export function preferencesMeta(payload) {
  const prefs = payload?.preferences || {};
  return {
    isSuperuser: Boolean(payload?.is_superuser),
    autoPauseLibraries: Array.isArray(prefs.auto_pause_libraries) ? prefs.auto_pause_libraries : [],
    choices: payload?.choices || {},
  };
}

export function preferencesPatch(values) {
  const patch = {};
  PREFERENCE_FIELDS.forEach(field => {
    if (!(field in (values || {}))) return;
    if (field === 'session_duration') {
      const number = Number(values[field]);
      if (Number.isFinite(number)) patch[field] = number;
      return;
    }
    if (field === 'auto_pause_in_progress_enabled') return;
    patch[field] = values[field];
  });
  if (Array.isArray(values?.auto_pause_rules)) {
    // The web form enables the feature while it has rules to apply.
    patch.auto_pause_in_progress_enabled = values.auto_pause_rules.length > 0;
  }
  return patch;
}

export function notificationsToForm(payload) {
  return {
    dailyDigestEnabled: Boolean(payload?.daily_digest_enabled),
    releaseNotificationsEnabled: Boolean(payload?.release_notifications_enabled),
    premiereNotificationsEnabled: Boolean(payload?.premiere_notifications_enabled),
    notificationUrlsConfigured: Boolean(payload?.notification_urls_configured),
    playbackWebhookConfigured: Boolean(payload?.playback_webhook_configured),
  };
}

export function notificationPatchFromForm(values) {
  const patch = {
    daily_digest_enabled: Boolean(values?.dailyDigestEnabled),
    release_notifications_enabled: Boolean(values?.releaseNotificationsEnabled),
    premiere_notifications_enabled: Boolean(values?.premiereNotificationsEnabled),
  };
  if (values?.notificationUrls) patch.notification_urls = values.notificationUrls;
  if (values?.playbackWebhookUrl) patch.playback_webhook_url = values.playbackWebhookUrl;
  if (values?.playbackWebhookSecret) patch.playback_webhook_secret = values.playbackWebhookSecret;
  return patch;
}

export function appearanceFromPayload(payload) {
  return {
    presets: payload?.presets || {},
    colors: payload?.colors || {},
    effects: payload?.effects || {},
    families: payload?.families || {},
    values: {
      theme: payload?.theme || 'system',
      palette: { ...(payload?.palette || {}) },
      layouts: payload?.layouts || {},
    },
  };
}

export function appearanceBody(values) {
  return {
    theme: values.theme,
    custom_theme: values.palette || {},
    detail_layouts: values.layouts || {},
  };
}

export function cardsFromPayload(payload) {
  return {
    catalog: payload?.catalog || [],
    values: { saved: payload?.profiles || {}, touchActions: Boolean(payload?.clickable_media_cards) },
  };
}

export function cardsBody(values) {
  return {
    card_metadata: { types: values.saved || {} },
    clickable_media_cards: Boolean(values.touchActions),
  };
}

export function homeFromPayload(payload) {
  const sections = (payload?.sections || []).map(section => {
    // The server's icon_svg is an HTML string; native never renders it.
    const { icon_svg: _icon, ...rest } = section;
    return rest;
  });
  return {
    sections,
    mediaTypeChipStyles: payload?.media_type_chip_styles || [],
    values: {
      sections,
      showMediaTypeHeaders: Boolean(payload?.show_media_type_headers),
      mediaTypeChipsEnabled: Boolean(payload?.media_type_chips_enabled),
      mediaTypeChipStyle: payload?.media_type_chip_style || '',
    },
  };
}

export function homeBody(values) {
  return {
    sections: values.sections || [],
    show_media_type_headers: Boolean(values.showMediaTypeHeaders),
    media_type_chips_enabled: Boolean(values.mediaTypeChipsEnabled),
    media_type_chip_style: values.mediaTypeChipStyle || undefined,
  };
}

function formatWhen(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function schedulesFromPayload(payload) {
  const labels = new Map((payload?.media_types || []).map(type => [type.value, type.label]));
  return {
    mediaTypes: payload?.media_types || [],
    schedules: (payload?.results || []).map(entry => ({
      id: entry.task_name,
      schedule: entry.frequency,
      mediaTypesLabel: (entry.media_types || []).map(value => labels.get(value) || value).join(', '),
      includeLists: Boolean(entry.include_lists),
      includeCollection: Boolean(entry.include_collection),
      lastRun: formatWhen(entry.last_run),
      nextRun: formatWhen(entry.next_run),
    })),
  };
}

export function scheduleBody(model) {
  return {
    frequency: model.frequency,
    time: model.time,
    media_types: model.selectedMediaTypes || [],
    include_lists: Boolean(model.includeLists),
    include_collection: Boolean(model.includeCollection),
  };
}

// media_types repeats, which the shared query helper cannot express.
export function exportPath(model) {
  const parts = (model.selectedMediaTypes || []).map(type => `media_types=${encodeURIComponent(type)}`);
  parts.push(`include_lists=${model.includeLists ? '1' : '0'}`);
  parts.push(`include_collection=${model.includeCollection ? '1' : '0'}`);
  return `/api/v1/export/csv/?${parts.join('&')}`;
}

export function historyFromPayload(payload) {
  return (payload?.results || []).map((entry, index) => ({
    id: `${entry.date || 'run'}-${index}`,
    status: entry.status,
    date: formatWhen(entry.date),
    summary: entry.summary || '',
  }));
}

export function rssFromPayload(payload) {
  return {
    mediaTypes: payload?.media_types || [],
    template: payload?.feed_url_template || '',
  };
}

export function rssFeedUrl(template, { mediaType, rowKey, skipPlanning, skipCollected }) {
  if (!template || !mediaType || !rowKey) return '';
  const base = template
    .replace('MEDIA_TYPE_PLACEHOLDER', mediaType)
    .replace('ROW_KEY_PLACEHOLDER', rowKey);
  return `${base}?skip_planning=${skipPlanning ? '1' : '0'}&skip_collected=${skipCollected ? '1' : '0'}`;
}

function formatDay(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

export function tokensFromPayload(payload) {
  const now = Date.now();
  return {
    tokens: (payload?.results || []).map(token => ({
      id: token.id,
      name: token.name,
      prefix: token.prefix,
      scopes: token.scopes || [],
      createdAt: formatDay(token.created_at),
      lastUsedAt: formatWhen(token.last_used_at),
      expiresAt: formatDay(token.expires_at),
      expired: Boolean(token.expires_at) && new Date(token.expires_at).getTime() <= now,
    })),
    scopes: (payload?.scope_choices || []).map(scope => ({ value: scope.value, description: scope.description })),
    presetScopes: (payload?.scope_choices || []).filter(scope => scope.default).map(scope => scope.value),
  };
}

export function grantsFromPayload(payload) {
  return (payload?.results || []).map(grant => ({
    id: grant.id,
    name: grant.name,
    createdAt: formatDay(grant.created_at),
    lastUsedAt: formatWhen(grant.last_used_at),
    allowPlaybackStart: Boolean(grant.allow_playback_start),
  }));
}

export function applicationsFromPayload(payload) {
  return (payload?.results || []).map(app => ({
    id: app.client_id,
    name: app.name,
    clientId: app.client_id,
    active: true,
    connectedAt: formatWhen(app.connected_at),
    lastUsedAt: formatWhen(app.last_used_at),
    scopes: (app.scopes || []).map(scope => ({ label: scope.label, description: scope.description })),
  }));
}

export function maskToken(token) {
  const value = String(token || '');
  if (!value) return '';
  return `${'•'.repeat(12)}${value.slice(-4)}`;
}

export function advancedFromPayload(payload) {
  const isSuperuser = Boolean(payload?.isSuperuser);
  return {
    isSuperuser,
    logs: {
      isSuperuser,
      logsSince: payload?.logsSince || '',
      lastUncleanExit: payload?.lastUncleanExit || '',
      bugReportUrl: payload?.bugReportUrl || '',
    },
    imageCache: {
      isSuperuser,
      enabled: Boolean(payload?.imageEnabled),
      count: payload?.imageCount || 0,
      size: payload?.imageSize || '0 B',
    },
    serverPort: { canManage: isSuperuser, ...(payload?.serverPort || {}) },
  };
}

export function absoluteUrl(serverUrl, path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  return `${String(serverUrl || '').replace(/\/+$/, '')}${path.startsWith('/') ? '' : '/'}${path}`;
}

export function aboutFromPayload(payload, serverUrl = '') {
  const releases = Array.isArray(payload?.releases) ? payload.releases : [];
  const specs = (payload?.specs || []).map(spec => ({ ...spec, path: spec.url, url: absoluteUrl(serverUrl, spec.url) }));
  return {
    version: payload?.version || '',
    commit: payload?.commit || '',
    releaseTag: payload?.releaseTag || '',
    updateAvailable: Boolean(payload?.updateAvailable),
    releases,
    releasesLoaded: Boolean(payload?.releasesLoaded),
    releasesUrl: payload?.releasesUrl || '',
    guideUrl: payload?.guideUrl || '',
    resources: payload?.resources || [],
    specs,
    attributions: payload?.attributions || [],
    licenses: payload?.licenses || [],
  };
}

export class SettingsSignedOutError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SettingsSignedOutError';
    this.code = 'signed_out';
  }
}

export function createRemoteSettingsActions(request, { authType = 'session' } = {}) {
  const canManageCredentials = authType === 'session';
  const get = (path, query) => request(path, query ? { query } : undefined);
  const send = (method, path, body) => request(path, { method, body: body === undefined ? {} : body });
  return {
    mode: 'server',
    canManageCredentials,
    loadAccess: async () => {
      const [account, tokens, applications] = await Promise.all([
        canManageCredentials ? get('/api/v1/user/token/') : Promise.resolve({ token: '' }),
        get('/api/v1/user/tokens/'),
        get('/api/v1/user/oauth-applications/'),
      ]);
      return { account, tokens, applications };
    },
    loadPreferences: () => get('/api/v1/user/preferences/'),
    loadPreferenceChoices: () => get('/api/v1/user/preferences/choices/'),
    savePreferences: values => send('PATCH', '/api/v1/user/preferences/', preferencesPatch(values)),
    savePlaybackWebhook: values => send('PATCH', '/api/v1/user/preferences/', values),
    loadNotifications: () => get('/api/v1/user/notifications/'),
    saveNotifications: values => send('PATCH', '/api/v1/user/notifications/', values),
    excludeNotificationItem: ({ itemId }) => send('POST', '/api/v1/user/notifications/exclusions/', { item_id: itemId }),
    searchNotificationItems: ({ search }) => get('/api/v1/media/', { search, limit: 20, offset: 0 }),
    includeNotificationItem: ({ itemId }) => send('DELETE', '/api/v1/user/notifications/exclusions/', { item_id: itemId }),
    loadNotificationExclusions: () => get('/api/v1/user/notifications/exclusions/'),
    testNotification: () => send('POST', '/api/v1/user/notifications/test/', {}),
    loadAppearance: () => get('/api/v1/user/appearance/'),
    saveAppearance: values => send('PUT', '/api/v1/user/appearance/', appearanceBody(values)),
    loadSidebar: () => get('/api/v1/user/sidebar/'),
    saveSidebar: ({ enabled, order, showDiscover }) => send('PUT', '/api/v1/user/sidebar/', {
      media_types: enabled,
      order,
      show_discover: Boolean(showDiscover),
    }),
    loadImportActivity: ({ page } = {}) => get('/api/v1/imports/activity/', page ? { page } : undefined),
    actImportActivity: ({ path, values }) => send('POST', '/api/v1/imports/activity/', { path, values }),
    loadCards: () => get('/api/v1/user/cards/'),
    saveCards: values => send('PUT', '/api/v1/user/cards/', cardsBody(values)),
    previewCard: ({ type, saved }) => send('POST', '/api/v1/user/cards/preview/', { type, draft: { types: saved || {} } }),
    loadHomeScreen: () => get('/api/v1/user/home-screen/'),
    saveHomeScreen: values => send('PUT', '/api/v1/user/home-screen/', homeBody(values)),
    searchHomeLists: ({ q = '', mediaType = '' } = {}) => get('/api/v1/user/home-screen/lists/', { q, media_type: mediaType }),
    loadHomeFilterFields: ({ mediaType }) => get('/api/v1/user/home-screen/filter-fields/', { media_type: mediaType }),
    loadAccountToken: () => get('/api/v1/user/token/'),
    regenerateAccountToken: () => send('POST', '/api/v1/user/token/regenerate/', {}),
    loadAppTokens: () => get('/api/v1/user/tokens/'),
    createAppToken: ({ name, scopes, expiresInDays }) => send('POST', '/api/v1/user/tokens/', {
      name,
      scopes,
      expires_in_days: expiresInDays === '' || expiresInDays == null ? undefined : Number(expiresInDays),
    }),
    revokeAppToken: ({ id }) => send('DELETE', `/api/v1/user/tokens/${encodeURIComponent(id)}/`),
    loadGrants: () => get('/api/v1/user/catalog-grants/'),
    createGrant: ({ name, allowPlaybackStart }) => send('POST', '/api/v1/user/catalog-grants/', {
      name,
      allow_playback_start: Boolean(allowPlaybackStart),
    }),
    revokeGrant: ({ id }) => send('DELETE', `/api/v1/user/catalog-grants/${encodeURIComponent(id)}/`),
    loadApplications: () => get('/api/v1/user/oauth-applications/'),
    revokeApplication: ({ clientId }) => send('DELETE', `/api/v1/user/oauth-applications/${encodeURIComponent(clientId)}/`),
    loadUsers: () => get('/api/v1/admin/users/'),
    createUser: values => send('POST', '/api/v1/admin/users/', values),
    updateUser: (id, values) => send('PATCH', `/api/v1/admin/users/${encodeURIComponent(id)}/`, values),
    setUserPassword: (id, values) => send('POST', `/api/v1/admin/users/${encodeURIComponent(id)}/password/`, values),
    deleteUser: id => send('DELETE', `/api/v1/admin/users/${encodeURIComponent(id)}/`),
    loadAdvanced: () => get('/api/v1/user/advanced/'),
    setImageCache: enabled => send('PUT', '/api/v1/user/advanced/image-cache/', { enabled: Boolean(enabled) }),
    clearImageCache: () => send('DELETE', '/api/v1/user/advanced/image-cache/'),
    clearCache: kind => send('DELETE', `/api/v1/user/advanced/caches/${encodeURIComponent(kind)}/`),
    saveServerPort: port => send('PUT', '/api/v1/user/advanced/server-port/', { port }),
    resetServerPort: () => send('DELETE', '/api/v1/user/advanced/server-port/'),
    downloadLogs: () => get('/api/v1/user/advanced/logs/'),
    downloadDiagnostics: () => get('/api/v1/user/advanced/diagnostics/'),
    loadAbout: () => get('/api/v1/user/about/'),
    loadSpecification: path => request(path, { headers: { Accept: 'text/plain, text/yaml, application/json, application/ld+json, */*' }, responseType: 'text' }),
    loadWhatsNew: () => get('/api/v1/user/about/whats-new/'),
    loadSchedules: () => get('/api/v1/exports/schedules/'),
    createSchedule: model => send('POST', '/api/v1/exports/schedules/', scheduleBody(model)),
    deleteSchedule: ({ id }) => send('DELETE', '/api/v1/exports/schedules/', { task_name: id }),
    loadExportHistory: () => get('/api/v1/exports/history/'),
    loadBackupStatus: () => get('/api/v1/exports/backup-status/'),
    exportLetterboxd: () => request('/api/v1/export/letterboxd/'),
    loadImportSettings: () => get('/api/v1/user/import-settings/'),
    saveImportSettings: values => send('PUT', '/api/v1/user/import-settings/', values),
    exportNow: model => request(exportPath(model)),
    downloadImportTemplate: () => get('/api/v1/export/template/'),
    restoreBackup: ({ content, mode }) => send('POST', '/api/v1/user/restore/', { content, mode }),
    loadRss: () => get('/api/v1/user/rss/'),
    loadRssPreview: ({ mediaType, rowKey, skipPlanning, skipCollected }) => get('/api/v1/user/rss/preview/', {
      media_type: mediaType,
      row_key: rowKey,
      skip_planning: skipPlanning ? '1' : '0',
      skip_collected: skipCollected ? '1' : '0',
    }),
    loadLibraryMaintenance: () => get('/api/v1/user/library-maintenance/'),
    runLibraryMaintenance: body => send('POST', '/api/v1/user/library-maintenance/', body),
  };
}

const ACTION_NAMES = Object.keys(createRemoteSettingsActions(() => Promise.resolve()));

// Signed out: every action rejects so a page shows its sign-in state instead
// of a fake success.
export function createLocalSettingsActions(reason) {
  const actions = { mode: 'local', reason, canManageCredentials: false };
  ACTION_NAMES.filter(name => name !== 'mode' && name !== 'canManageCredentials').forEach(name => {
    actions[name] = async () => { throw new SettingsSignedOutError(reason); };
  });
  return actions;
}
