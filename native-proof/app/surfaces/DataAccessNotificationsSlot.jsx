import React, { useEffect, useState } from 'react';
import { SettingsAccessView } from '../../../frontend/pages/SettingsAccessView';
import { SettingsDataView } from '../../../frontend/pages/SettingsDataView';
import { SettingsNotificationsView } from '../../../frontend/pages/SettingsNotificationsView';
import {
  createSettingsTransport,
  notificationPatchFromForm,
  notificationsToForm,
} from '../data/settingsTransport';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SET-DATA',
  title: 'Data, access and notification settings',
  where: 'Settings data export, RSS, access tokens, OAuth grants and notifications',
  status: 'ported',
  note: 'Export schedules and history, restore, RSS building, access tokens, install credentials, OAuth grants and notification preferences render from shared React Native components. The Notifications page reads /api/v1/user/notifications/ and its exclusion list, saves through the same route and the playback webhook through /api/v1/user/preferences/, and searches tracked items through /api/v1/media/. Export, restore, RSS, access tokens, install credentials and OAuth grants still have no JSON read/write endpoints, so those sections keep their demo state. Secure credential storage and iOS/Android runtime verification remain unverified.',
};

const settingsPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  border: palette.border,
  background: palette.surface,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  radius: radius.md,
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(239, 68, 68, 0.18)', hovered: 'rgba(239, 68, 68, 0.18)', text: '#f87171', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const exportMediaTypes = [
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'TV Shows' },
  { value: 'anime', label: 'Anime' },
  { value: 'book', label: 'Books' },
  { value: 'game', label: 'Games' },
];

const exportHistory = [
  { id: 'run-1042', status: 'SUCCESS', date: 'Nov 1, 2026, 03:00', summary: 'Exported 1,284 entries to floppy-export-2026-11-01.csv.' },
  { id: 'run-1041', status: 'FAILURE', date: 'Oct 31, 2026, 03:00', summary: 'Export stopped before writing the collection.', errors: 'Could not read the artwork cache.\nThe CSV was not written.' },
  { id: 'run-1040', status: 'STARTED', date: 'Oct 30, 2026, 03:00', summary: 'Export started in the background.' },
];

const rssRows = {
  movie: [
    { value: 'trending_right_now', label: 'Trending Right Now' },
    { value: 'all_time_greats', label: 'All-Time Greats' },
    { value: 'coming_soon', label: 'Coming Soon' },
  ],
  tv: [
    { value: 'trending_right_now', label: 'Trending Right Now' },
    { value: 'coming_soon', label: 'Coming Soon' },
  ],
  anime: [
    { value: 'trending_right_now', label: 'Trending Right Now' },
    { value: 'coming_soon', label: 'Coming Soon' },
  ],
};

const rssPreviewItems = [
  { id: 'p1', title: 'The Last Signal', subtitle: 'Movie · 2026 · Science fiction' },
  { id: 'p2', title: 'Harbour Lights', subtitle: 'Movie · 2026 · Drama' },
  { id: 'p3', title: 'Northbound', subtitle: 'Movie · 2026 · Adventure' },
];

const demoAppTokens = [
  { id: 'tok-1', name: 'Nuvio living room', prefix: 'flp_live_7d2c', scopes: ['library:read', 'progress:write', 'lists:read'], createdAt: 'Oct 24, 2026', lastUsedAt: 'Today, 18:12', expiresAt: 'Jan 22, 2027', expired: false },
  { id: 'tok-2', name: 'Tablet scrobbler', prefix: 'flp_tab_19ad', scopes: ['progress:write', 'history:read'], createdAt: 'Jun 2, 2026', lastUsedAt: '', expiresAt: 'Sep 1, 2026', expired: true },
];

const demoScopes = [
  { value: 'library:read', description: 'Read your tracked media and progress.' },
  { value: 'progress:write', description: 'Scrobble plays and update progress.' },
  { value: 'history:read', description: 'Read playback history.' },
  { value: 'lists:read', description: 'Read custom lists and saved items.' },
];

const demoGrants = [
  { id: 'grant-1', name: 'Living room TV', createdAt: 'Oct 12, 2026', lastUsedAt: 'Yesterday, 20:40', allowPlaybackStart: true },
  { id: 'grant-2', name: 'Shield catalog only', createdAt: 'Sep 8, 2026', lastUsedAt: '', allowPlaybackStart: false },
];

const demoApplications = [
  { id: 'app-1', name: 'Nuvio', clientId: 'flp_oauth_nuvio_91b2', active: true, connectedAt: 'Oct 2, 2026, 14:20', lastUsedAt: 'Today, 17:58', scopes: [{ label: 'Library', description: 'Read tracked media and progress.' }, { label: 'Progress', description: 'Scrobble plays and update progress.' }] },
  { id: 'app-2', name: 'Tiny Media Manager', clientId: 'flp_oauth_tmm_402c', active: false, connectedAt: 'Aug 19, 2026, 09:12', lastUsedAt: '', scopes: [{ label: 'Lists', description: 'Read custom lists and collection exports.' }] },
];

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function DataAccessNotificationsSlot({ page = 'data' }) {
  const [transport] = useState(() => createSettingsTransport());
  const [exportModel, setExportModel] = useState({
    frequency: 'weekly',
    time: '03:00',
    mediaTypes: exportMediaTypes,
    selectedMediaTypes: ['movie', 'tv'],
    includeLists: true,
    includeCollection: false,
  });
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState('');
  const [exportSuccess, setExportSuccess] = useState('');
  const [schedules, setSchedules] = useState([{ id: 's1', schedule: 'Every week', mediaTypesLabel: 'TV Shows, Movies', includeLists: true, includeCollection: false, lastRun: 'Nov 1, 2026, 03:00', nextRun: 'Nov 8, 2026, 03:00' }]);
  const [scheduleBusyId, setScheduleBusyId] = useState('');
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleSuccess, setScheduleSuccess] = useState('');
  const [restoreFileName, setRestoreFileName] = useState('');
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [restoreError, setRestoreError] = useState('');
  const [restoreSuccess, setRestoreSuccess] = useState('');
  const [rssValues, setRssValues] = useState({ mediaType: 'movie', rowKey: 'trending_right_now', skipPlanning: true, skipCollected: true });
  const [rssSuccess, setRssSuccess] = useState('');
  const [tokenBusy, setTokenBusy] = useState(false);
  const [tokenError, setTokenError] = useState('');
  const [tokenSuccess, setTokenSuccess] = useState('');
  const [appTokens, setAppTokens] = useState(demoAppTokens);
  const [oneTimeSecret, setOneTimeSecret] = useState(null);
  const [appTokensBusy, setAppTokensBusy] = useState(false);
  const [appTokensError, setAppTokensError] = useState('');
  const [appTokensSuccess, setAppTokensSuccess] = useState('');
  const [grants, setGrants] = useState(demoGrants);
  const [grantsBusy, setGrantsBusy] = useState(false);
  const [grantsError, setGrantsError] = useState('');
  const [grantsSuccess, setGrantsSuccess] = useState('');
  const [applications, setApplications] = useState(demoApplications);
  const [applicationsBusy, setApplicationsBusy] = useState(false);
  const [applicationsError, setApplicationsError] = useState('');
  const [applicationsSuccess, setApplicationsSuccess] = useState('');
  const [notificationValues, setNotificationValues] = useState({
    notificationUrls: '',
    playbackWebhookUrl: '',
    playbackWebhookSecret: '',
    dailyDigestEnabled: false,
    releaseNotificationsEnabled: false,
    premiereNotificationsEnabled: false,
  });
  const [notificationStored, setNotificationStored] = useState({
    notificationUrls: false, notificationUrlCount: null, playbackWebhookUrl: false, playbackWebhookSecret: false,
  });
  const [notificationDirty, setNotificationDirty] = useState(false);
  const [notificationBusy, setNotificationBusy] = useState(false);
  const [notificationError, setNotificationError] = useState('');
  const [notificationSuccess, setNotificationSuccess] = useState('');
  const [excludedQuery, setExcludedQuery] = useState('');
  const [excludedSearching, setExcludedSearching] = useState(false);
  const [excludedResults, setExcludedResults] = useState([]);
  const [excludedItems, setExcludedItems] = useState([]);
  const [excludedBusyId, setExcludedBusyId] = useState('');
  const [excludedError, setExcludedError] = useState('');
  const [excludedSuccess, setExcludedSuccess] = useState('');

  useEffect(() => {
    if (page !== 'notifications' || transport.mode !== 'server') return undefined;
    let active = true;
    Promise.all([
      transport.loadNotifications(),
      transport.loadNotificationExclusions(),
    ]).then(([settings, exclusions]) => {
      if (!active) return;
      const mapped = notificationsToForm(settings);
      setNotificationValues(current => ({ ...current, ...mapped }));
      setNotificationStored({
        notificationUrls: mapped.notificationUrlsConfigured,
        notificationUrlCount: null,
        playbackWebhookUrl: false,
        playbackWebhookSecret: false,
      });
      setExcludedItems((exclusions?.results || []).map(item => ({
        id: item.item_id,
        title: item.title,
        mediaType: item.media_type,
      })));
    }).catch(cause => {
      if (active) setNotificationError(cause?.message || 'Notification settings could not be loaded.');
    });
    return () => { active = false; };
  }, [page, transport]);

  const rssFeedUrl = rssValues.mediaType && rssValues.rowKey
    ? `https://floppy.example.com/rss/${rssValues.mediaType}/${rssValues.rowKey}.xml?skip_planning=${rssValues.skipPlanning ? '1' : '0'}&skip_collected=${rssValues.skipCollected ? '1' : '0'}`
    : '';

  async function submitExport() {
    setExportError('');
    setExportSuccess('');
    setExportBusy(true);
    try {
      await wait(450);
      setExportSuccess(exportModel.frequency === 'once' ? 'Export started. The CSV will download when it is ready.' : 'Export saved. The first CSV is being written now.');
    } catch {
      setExportError('Could not start the export.');
    } finally {
      setExportBusy(false);
    }
  }

  async function deleteSchedule(schedule) {
    setScheduleBusyId(schedule.id);
    setScheduleError('');
    setScheduleSuccess('');
    await wait(350);
    setSchedules(current => current.filter(item => item.id !== schedule.id));
    setScheduleBusyId('');
    setScheduleSuccess(`${schedule.schedule} schedule deleted.`);
  }

  async function restoreBackup() {
    setRestoreBusy(true);
    setRestoreError('');
    setRestoreSuccess('');
    await wait(500);
    setRestoreBusy(false);
    setRestoreSuccess('Backup verified. Restore queued; the current library is replaced when the job finishes.');
  }

  function chooseBackup() {
    setRestoreError('');
    setRestoreSuccess('');
    setRestoreFileName('floppy-backup-2026-10-31.zip');
  }

  async function copyRssFeed() {
    setRssSuccess('Feed URL copied.');
    await wait(1200);
    setRssSuccess('');
  }

  async function regenerateToken() {
    setTokenBusy(true);
    setTokenError('');
    setTokenSuccess('');
    await wait(400);
    setTokenBusy(false);
    setTokenSuccess('API token regenerated. Update your webhooks and feed links.');
  }

  async function createAppToken({ name, expiresInDays, scopes }) {
    setAppTokensBusy(true);
    setAppTokensError('');
    setAppTokensSuccess('');
    await wait(400);
    const id = `tok-${Date.now()}`;
    setAppTokens(current => [{ id, name, prefix: `flp_${id.slice(-4)}`, scopes, createdAt: 'Just now', lastUsedAt: '', expiresAt: expiresInDays ? `${expiresInDays} days` : '', expired: false }, ...current]);
    setOneTimeSecret({ name, preview: `flp_${id.slice(-4)}…` });
    setAppTokensBusy(false);
    setAppTokensSuccess(`Token created: ${name}. Copy the secret now.`);
  }

  async function revokeAppToken(token) {
    setAppTokensBusy(true);
    setAppTokensError('');
    setAppTokensSuccess('');
    await wait(300);
    setAppTokens(current => current.filter(item => item.id !== token.id));
    setAppTokensBusy(false);
    setAppTokensSuccess(`${token.name} revoked.`);
  }

  function copyOneTimeSecret() {
    setAppTokensSuccess('One-time secret copied.');
  }

  async function createGrant({ name, allowPlaybackStart }) {
    setGrantsBusy(true);
    setGrantsError('');
    setGrantsSuccess('');
    await wait(350);
    setGrants(current => [{ id: `grant-${Date.now()}`, name, createdAt: 'Just now', lastUsedAt: '', allowPlaybackStart }, ...current]);
    setGrantsBusy(false);
    setGrantsSuccess(`Install credential created for ${name}.`);
  }

  async function revokeGrant(grant) {
    setGrantsBusy(true);
    setGrantsError('');
    setGrantsSuccess('');
    await wait(300);
    setGrants(current => current.filter(item => item.id !== grant.id));
    setGrantsBusy(false);
    setGrantsSuccess(`${grant.name} revoked.`);
  }

  async function revokeApplication(application) {
    setApplicationsBusy(true);
    setApplicationsError('');
    setApplicationsSuccess('');
    await wait(300);
    setApplications(current => current.filter(item => item.id !== application.id));
    setApplicationsBusy(false);
    setApplicationsSuccess(`Access for ${application.name} revoked.`);
  }

  function changeNotifications(values) {
    setNotificationValues(values);
    setNotificationDirty(true);
    setNotificationSuccess('');
    setNotificationError('');
  }

  async function saveNotifications() {
    setNotificationBusy(true);
    setNotificationError('');
    setNotificationSuccess('');
    if (transport.mode !== 'server') {
      await wait(400);
      setNotificationBusy(false);
      setNotificationDirty(false);
      setNotificationSuccess('Sign in to save notification settings.');
      return;
    }
    try {
      await transport.saveNotifications(notificationPatchFromForm(notificationValues));
      const webhook = {};
      if (notificationValues.playbackWebhookUrl) webhook.playback_webhook_url = notificationValues.playbackWebhookUrl;
      if (notificationValues.playbackWebhookSecret) webhook.playback_webhook_secret = notificationValues.playbackWebhookSecret;
      if (Object.keys(webhook).length) await transport.savePlaybackWebhook(webhook);
      setNotificationStored(current => ({
        ...current,
        notificationUrls: current.notificationUrls || Boolean(notificationValues.notificationUrls),
        playbackWebhookUrl: current.playbackWebhookUrl || Boolean(notificationValues.playbackWebhookUrl),
        playbackWebhookSecret: current.playbackWebhookSecret || Boolean(notificationValues.playbackWebhookSecret),
      }));
      setNotificationValues(current => ({ ...current, playbackWebhookSecret: '' }));
      setNotificationDirty(false);
      setNotificationSuccess('Notification settings saved.');
    } catch (cause) {
      setNotificationError(cause?.message || 'Notification settings could not be saved.');
    } finally {
      setNotificationBusy(false);
    }
  }

  async function testNotifications() {
    setNotificationBusy(true);
    setNotificationError('');
    setNotificationSuccess('');
    if (transport.mode !== 'server') {
      await wait(500);
      setNotificationBusy(false);
      setNotificationSuccess('Sign in to send a test notification.');
      return;
    }
    try {
      await transport.testNotification();
      setNotificationSuccess('Test notification queued.');
    } catch (cause) {
      setNotificationError(cause?.message || 'The test notification could not be sent.');
    } finally {
      setNotificationBusy(false);
    }
  }

  function searchExcluded(query) {
    setExcludedQuery(query);
    setExcludedSuccess('');
    setExcludedError('');
    if (query.trim().length <= 1) {
      setExcludedResults([]);
      setExcludedSearching(false);
      return;
    }
    if (transport.mode !== 'server') {
      setExcludedResults([]);
      setExcludedSearching(false);
      return;
    }
    setExcludedSearching(true);
    transport.searchNotificationItems({ search: query.trim() })
      .then(payload => {
        const excludedIds = new Set(excludedItems.map(item => item.id));
        setExcludedResults((payload?.results || [])
          .map(result => ({
            id: result.id,
            title: result.item?.title || result.title || '',
            mediaType: result.item?.library_media_type || result.item?.media_type || '',
          }))
          .filter(item => !excludedIds.has(item.id)));
      })
      .catch(cause => setExcludedError(cause?.message || 'Search failed.'))
      .finally(() => setExcludedSearching(false));
  }

  async function excludeItem(item) {
    setExcludedBusyId(item.id);
    setExcludedError('');
    setExcludedSuccess('');
    if (transport.mode !== 'server') {
      setExcludedBusyId('');
      setExcludedError('Sign in to exclude items from notifications.');
      return;
    }
    try {
      await transport.excludeNotificationItem({ itemId: item.id });
      setExcludedItems(current => [...current, item]);
      setExcludedResults(current => current.filter(result => result.id !== item.id));
      setExcludedSuccess(`${item.title} excluded from notifications.`);
    } catch (cause) {
      setExcludedError(cause?.message || 'Could not exclude that item.');
    } finally {
      setExcludedBusyId('');
    }
  }

  async function includeItem(item) {
    setExcludedBusyId(item.id);
    setExcludedError('');
    setExcludedSuccess('');
    if (transport.mode !== 'server') {
      setExcludedBusyId('');
      setExcludedError('Sign in to include items in notifications.');
      return;
    }
    try {
      await transport.includeNotificationItem({ itemId: item.id });
      setExcludedItems(current => current.filter(result => result.id !== item.id));
      setExcludedSuccess(`${item.title} included in notifications again.`);
    } catch (cause) {
      setExcludedError(cause?.message || 'Could not include that item.');
    } finally {
      setExcludedBusyId('');
    }
  }

  const rssModel = {
    mediaTypes: [
      { value: 'movie', label: 'Movies' },
      { value: 'tv', label: 'TV Shows' },
      { value: 'anime', label: 'Anime' },
    ],
    rows: rssRows[rssValues.mediaType] || [],
    values: rssValues,
    feedUrl: rssFeedUrl,
    preview: { state: 'ready', title: 'Movies · Trending Right Now', items: rssPreviewItems },
  };

  if (page === 'access') {
    return <SettingsAccessView
      accountToken={{
        maskedToken: '••••••••••••', busy: tokenBusy, error: tokenError,
        success: tokenSuccess, onCopy: () => setTokenSuccess('API token copied.'),
        onRegenerate: regenerateToken,
      }}
      appTokens={{
        model: {
          tokens: appTokens,
          scopes: demoScopes,
          presetScopes: ['library:read', 'progress:write', 'lists:read'],
          oneTimeSecret,
        },
        busy: appTokensBusy, error: appTokensError, success: appTokensSuccess,
        onCreate: createAppToken, onRevoke: revokeAppToken, onCopySecret: copyOneTimeSecret,
      }}
      catalogGrants={{
        grants, busy: grantsBusy, error: grantsError, success: grantsSuccess,
        onCreate: createGrant, onRevoke: revokeGrant,
      }}
      applications={{
        applications, busy: applicationsBusy, error: applicationsError,
        success: applicationsSuccess, onRevoke: revokeApplication,
      }}
      palette={settingsPalette} buttonPalette={buttonPalette} />;
  }

  if (page === 'notifications') {
    return <SettingsNotificationsView
      preferences={{
        model: {
          values: notificationValues,
          stored: notificationStored,
          dirty: notificationDirty,
        },
        busy: notificationBusy, error: notificationError, success: notificationSuccess,
        onChange: changeNotifications, onSave: saveNotifications, onTest: testNotifications,
      }}
      excluded={{
        model: { query: excludedQuery, searching: excludedSearching, results: excludedResults, excluded: excludedItems },
        busyId: excludedBusyId, error: excludedError, success: excludedSuccess,
        onSearchChange: searchExcluded, onExclude: excludeItem, onInclude: includeItem,
      }}
      palette={settingsPalette} buttonPalette={buttonPalette} />;
  }

  return <SettingsDataView
    schedule={{
      model: exportModel, busy: exportBusy, error: exportError, success: exportSuccess,
      onChange: setExportModel, onSubmit: submitExport,
    }}
    scheduled={{
      schedules, busyId: scheduleBusyId, error: scheduleError, success: scheduleSuccess,
      onDelete: deleteSchedule,
    }}
    history={{ results: exportHistory }}
    restore={{
      fileName: restoreFileName, busy: restoreBusy, error: restoreError,
      success: restoreSuccess, onChoose: chooseBackup, onRestore: restoreBackup,
    }}
    rss={{
      model: rssModel, success: rssSuccess, onChange: setRssValues, onCopy: copyRssFeed,
    }}
    palette={settingsPalette} buttonPalette={buttonPalette} />;
}
