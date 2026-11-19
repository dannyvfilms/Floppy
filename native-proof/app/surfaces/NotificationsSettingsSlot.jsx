import React, { useRef, useState } from 'react';
import { Linking } from 'react-native';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { settingsNavIcons } from '../settingsNavIcons';
import { SettingsNotificationsView } from '../../../frontend/pages/SettingsNotificationsView';
import { absoluteUrl, notificationPatchFromForm, notificationsToForm } from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

// The web page's wording (templates/users/notifications.html).
const WEB_COPY = {
  description: 'Configure how you want to receive notifications about your media.',
  apprisePlaceholder: 'discord://webhook_id/webhook_token\ntgram://bot_token/chat_id\nnotifiarr://api_key/#channel_id',
  searchPlaceholder: 'Search for media to exclude...',
  noExcluded: 'No media items excluded yet',
  appriseHelp: 'Enter each Apprise URL on a separate line to send notifications to multiple services.',
  playbackWebhook: 'Playback Webhook',
  playbackWebhookHelp: 'POSTs the live playback state to this URL whenever it changes, with the same body /api/v1/playback/now-playing/ returns. For home automation or a client that wants playback pushed to it rather than polled. Leave blank to send nothing.',
  secretHelp: 'Optional shared secret. When set, each request carries X-Floppy-Signature: sha256=<hmac> over the exact body sent, so the receiver can verify it came from you. Leave blank to keep the current secret; clear the URL above to turn the webhook off.',
  settings: 'Notification Settings',
  dailyDigestHelp: 'Receive a single notification each day with all media scheduled to release that day',
  releaseNotifications: 'Receive notifications for recently released media',
  releaseNotificationsHelp: 'Get notified when new episodes, chapters, or other media are released',
  premiereNotificationsHelp: 'Receive a weekly digest of new show and season premieres',
  test: 'Test Notifications',
  save: 'Save Settings',
  excludedTitle: 'Excluded Media Items',
  excludedDescription: 'Exclude specific media items from notifications:',
};

function mapExcluded(payload, serverUrl) {
  return (payload?.results || []).map(item => ({ id: item.item_id, title: item.title,
    mediaType: item.media_type_label || item.media_type, image: absoluteUrl(serverUrl, item.image) }));
}

function NotificationsForm({ transport, settings, exclusions }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const mapped = notificationsToForm(settings);
  const [values, setValues] = useState({
    notificationUrls: '', playbackWebhookUrl: '', playbackWebhookSecret: '',
    dailyDigestEnabled: mapped.dailyDigestEnabled,
    releaseNotificationsEnabled: mapped.releaseNotificationsEnabled,
    premiereNotificationsEnabled: mapped.premiereNotificationsEnabled,
  });
  const [stored, setStored] = useState({
    notificationUrls: mapped.notificationUrlsConfigured, notificationUrlCount: null,
    playbackWebhookUrl: mapped.playbackWebhookConfigured, playbackWebhookSecret: mapped.playbackWebhookConfigured,
  });
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState([]);
  const [excluded, setExcluded] = useState(() => mapExcluded(exclusions, transport.serverUrl));
  const querySequence = useRef(0);
  const [busyId, setBusyId] = useState('');
  const [excludedError, setExcludedError] = useState('');
  const [excludedSuccess, setExcludedSuccess] = useState('');

  function change(next) {
    setValues(next);
    setDirty(true);
    setSuccess('');
    setError('');
  }

  async function save() {
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      const response = await transport.saveNotifications(notificationPatchFromForm(values));
      const fresh = notificationsToForm(response);
      setStored({
        notificationUrls: fresh.notificationUrlsConfigured, notificationUrlCount: null,
        playbackWebhookUrl: fresh.playbackWebhookConfigured, playbackWebhookSecret: fresh.playbackWebhookConfigured,
      });
      setValues(current => ({
        ...current, notificationUrls: '', playbackWebhookUrl: '', playbackWebhookSecret: '',
        dailyDigestEnabled: fresh.dailyDigestEnabled,
        releaseNotificationsEnabled: fresh.releaseNotificationsEnabled,
        premiereNotificationsEnabled: fresh.premiereNotificationsEnabled,
      }));
      setDirty(false);
      setSuccess('Notification settings updated successfully!');
    } catch (cause) {
      setError(cause?.errors?.notification_urls?.[0] || cause?.message || 'Notification settings could not be saved.');
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      await transport.testNotification();
      setSuccess('Test notification sent successfully!');
    } catch (cause) {
      setError(cause?.message || 'The test notification could not be sent.');
    } finally {
      setBusy(false);
    }
  }

  function search(text) {
    const request = ++querySequence.current;
    setQuery(text);
    setExcludedSuccess('');
    setExcludedError('');
    if (text.trim().length <= 1) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    transport.searchNotificationItems({ search: text.trim() })
      .then(payload => {
        if (request !== querySequence.current) return;
        const excludedIds = new Set(excluded.map(item => item.id));
        setResults((payload?.results || [])
          .map(result => ({
            id: result.id,
            title: result.item?.title || result.title || '',
            mediaType: result.item?.library_media_type || result.item?.media_type || '',
            image: absoluteUrl(transport.serverUrl, result.item?.image),
          }))
          .filter(item => item.id != null && !excludedIds.has(item.id)));
      })
      .catch(cause => { if (request === querySequence.current) setExcludedError(cause?.message || 'Search failed.'); })
      .finally(() => { if (request === querySequence.current) setSearching(false); });
  }

  async function exclude(item) {
    setBusyId(item.id);
    setExcludedError('');
    setExcludedSuccess('');
    try {
      await transport.excludeNotificationItem({ itemId: item.id });
      setExcluded(mapExcluded(await transport.loadNotificationExclusions(), transport.serverUrl));
      setResults(current => current.filter(result => result.id !== item.id));
      setExcludedSuccess(`${item.title} excluded from notifications.`);
    } catch (cause) {
      setExcludedError(cause?.message || 'Could not exclude that item.');
    } finally {
      setBusyId('');
    }
  }

  async function include(item) {
    setBusyId(item.id);
    setExcludedError('');
    setExcludedSuccess('');
    try {
      await transport.includeNotificationItem({ itemId: item.id });
      setExcluded(current => current.filter(result => result.id !== item.id));
      setExcludedSuccess(`${item.title} included in notifications again.`);
    } catch (cause) {
      setExcludedError(cause?.message || 'Could not include that item.');
    } finally {
      setBusyId('');
    }
  }

  return <SettingsNotificationsView
    heading={false}
    preferences={{
      icon: <Icon spec={settingsNavIcons.bell} color={settingsPalette.link} size={24} />,
      testIcon: settingsNavIcons.bell,
      model: { values, stored, dirty, labels: WEB_COPY, icons: { dailyDigest: actionIcons.alarmClock, releaseNotifications: actionIcons.bellRinging, premiereNotifications: actionIcons.calendar } },
      busy, error, success,
      onChange: change, onSave: save, onTest: test,
      onOpenLink: url => Linking.openURL(url).catch(() => setError('Could not open that link.')),
    }}
    excluded={{
      icon: <Icon spec={actionIcons.funnel} color={settingsPalette.link} size={24} />,
      model: { query, searching, results, excluded, labels: WEB_COPY },
      busyId, error: excludedError, success: excludedSuccess,
      onSearchChange: search, onExclude: exclude, onInclude: include,
    }}
    palette={{ ...settingsPalette, pageCards: true }} buttonPalette={buttonPalette} />;
}

export default function NotificationsSettingsSlot() {
  const resource = useSettingsResource(async transport => {
    const [settings, exclusions] = await Promise.all([
      transport.loadNotifications(),
      transport.loadNotificationExclusions(),
    ]);
    return { settings, exclusions };
  });
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <NotificationsForm transport={resource.transport} settings={resource.data.settings}
    exclusions={resource.data.exclusions} />;
}
