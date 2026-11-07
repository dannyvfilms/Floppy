import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../ui/Button';
import { FormSaveBar } from '../ui/FormSaveBar';
import { Spinner } from '../ui/Spinner';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';
import { SettingsCard } from './SettingsCard';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 6,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(220, 38, 38, 0.18)', hovered: 'rgba(220, 38, 38, 0.18)', text: '#f87171', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

const defaultLabels = {
  title: 'Notifications',
  description: 'Configure how Floppy notifies you about your media.',
  apprise: 'Apprise URLs',
  appriseHelp: 'Enter one URL per line. Discord, Notifiarr, Telegram, Slack, email, Pushover, ntfy and many more are supported.',
  apprisePlaceholder: 'discord://webhook_id/webhook_token',
  storedUrls: 'saved URLs',
  playbackWebhook: 'Playback webhook',
  playbackWebhookUrl: 'Webhook URL',
  playbackWebhookSecret: 'Shared secret',
  playbackWebhookHelp: 'POSTs live playback state whenever it changes. Leave the URL blank to turn the webhook off.',
  secretHelp: 'When set, each request carries an HMAC signature so the receiver can verify it. Leave blank to keep the current secret.',
  settings: 'Notification settings',
  dailyDigest: 'Enable Daily Digest',
  dailyDigestHelp: 'One notification each day with media scheduled to release that day.',
  releaseNotifications: 'Recently released media',
  releaseNotificationsHelp: 'Get notified when new episodes, chapters or other media are released.',
  premiereNotifications: 'Enable Premiere Digest',
  premiereNotificationsHelp: 'A weekly digest of new show and season premieres.',
  test: 'Test notifications',
  testing: 'Sending test…',
  save: 'Save settings',
  savedTitle: 'Notification settings saved',
  dirtyTitle: 'Unsaved notification changes',
  dirtyCopy: 'Save to apply your notification choices.',
  savingCopy: 'Applying your notification choices…',
  errorTitle: 'Could not save notifications',
  excludedTitle: 'Excluded media items',
  excludedDescription: 'Exclude specific media items from notifications.',
  searchPlaceholder: 'Search for media to exclude…',
  search: 'Search',
  searching: 'Searching…',
  noResults: 'No matching items found.',
  noExcluded: 'No media items excluded yet.',
  exclude: 'Exclude',
  remove: 'Remove',
  emptySearch: 'Type at least two characters to search.',
};

function MultiLineField({ id, label, help, value, placeholder, disabled, palette, onChangeText }) {
  return <View style={styles.field}>
    <Text nativeID={id ? `${id}-label` : undefined} style={[styles.label, { color: palette.textMuted }]}>{label}</Text>
    {help ? <Text style={[styles.copy, { color: palette.textMuted }]}>{help}</Text> : null}
    <TextInput
      accessibilityLabel={label}
      autoCapitalize="none"
      autoCorrect={false}
      editable={!disabled}
      multiline
      nativeID={id}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={palette.textMuted}
      value={value ?? ''}
      style={[styles.multiline, {
        backgroundColor: palette.surface,
        borderColor: palette.border,
        color: palette.textSecondary,
        opacity: disabled ? 0.5 : 1,
      }]}
    />
  </View>;
}

export function NotificationPreferencesCard({
  model = {},
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onChange,
  onSave,
  onTest,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const values = model.values || {};
  const stored = model.stored || {};
  const dirty = model.dirty ?? false;
  const [testing, setTesting] = useState(false);
  const update = changes => onChange?.({ ...values, ...changes });

  async function test() {
    setTesting(true);
    try {
      await onTest?.();
    } finally {
      setTesting(false);
    }
  }

  const savedDescription = stored.notificationUrls
    ? `Leave blank to keep the ${stored.notificationUrlCount || 1} ${labels.storedUrls}.`
    : labels.appriseHelp;

  return <SettingsCard title={labels.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.description}</Text>
    <MultiLineField id="notification-urls" label={labels.apprise} help={savedDescription}
      value={values.notificationUrls} placeholder={labels.apprisePlaceholder}
      disabled={busy} palette={colors} onChangeText={value => update({ notificationUrls: value })} />
    <View style={[styles.group, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.playbackWebhook}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.playbackWebhookHelp}</Text>
      <TextField label={labels.playbackWebhookUrl} name="playback_webhook_url" type="url"
        value={values.playbackWebhookUrl} placeholder={stored.playbackWebhookUrl ? 'Leave blank to keep the saved URL' : 'https://example.com/playback'}
        disabled={busy} palette={colors} onChangeText={value => update({ playbackWebhookUrl: value })} />
      <TextField label={labels.playbackWebhookSecret} name="playback_webhook_secret" type="password"
        value={values.playbackWebhookSecret} maskedPreview={stored.playbackWebhookSecret ? '••••••••' : undefined}
        placeholder={stored.playbackWebhookSecret ? 'Leave blank to keep the current secret' : 'Optional shared secret'}
        help={labels.secretHelp} disabled={busy} palette={colors}
        onChangeText={value => update({ playbackWebhookSecret: value })} />
    </View>
    <View style={[styles.group, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.settings}</Text>
      <ToggleChip label={labels.dailyDigest} help={labels.dailyDigestHelp} value={Boolean(values.dailyDigestEnabled)}
        offLabel="Off" onLabel="On" palette={colors} disabled={busy}
        onChange={value => update({ dailyDigestEnabled: value })} />
      <ToggleChip label={labels.releaseNotifications} help={labels.releaseNotificationsHelp}
        value={Boolean(values.releaseNotificationsEnabled)} offLabel="Off" onLabel="On"
        palette={colors} disabled={busy} onChange={value => update({ releaseNotificationsEnabled: value })} />
      <ToggleChip label={labels.premiereNotifications} help={labels.premiereNotificationsHelp}
        value={Boolean(values.premiereNotificationsEnabled)} offLabel="Off" onLabel="On"
        palette={colors} disabled={busy} onChange={value => update({ premiereNotificationsEnabled: value })} />
    </View>
    {success ? <Text accessibilityLiveRegion="polite" style={[styles.status, { color: colors.success }]}>{success}</Text> : null}
    <View style={styles.actions}>
      <Button label={testing ? labels.testing : labels.test} tone="surface" busy={testing}
        disabled={testing || busy} onPress={test} palette={buttons} />
    </View>
    <FormSaveBar dirty={dirty} saving={busy && !testing} error={error} onSave={onSave} saveLabel={labels.save}
      labels={{
        savedTitle: labels.savedTitle,
        dirtyTitle: labels.dirtyTitle,
        dirtyCopy: labels.dirtyCopy,
        savingCopy: labels.savingCopy,
        errorTitle: labels.errorTitle,
        save: labels.save,
        saving: 'Saving…',
      }}
      palette={colors} buttonPalette={buttons} />
  </SettingsCard>;
}

export function ExcludedMediaCard({
  model = {},
  busyId,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onSearchChange,
  onExclude,
  onInclude,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const results = model.results || [];
  const excluded = model.excluded || [];
  const query = model.query || '';

  return <SettingsCard title={labels.excludedTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.excludedDescription}</Text>
    <TextField label={labels.search} labelHidden name="notification_search" value={query}
      placeholder={labels.searchPlaceholder} palette={colors}
      onChangeText={value => onSearchChange?.(value)} />
    <View style={[styles.resultsBox, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      {model.searching ? <View style={styles.searchingRow}><Spinner size={16} color={colors.accent} />
        <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.searching}</Text></View>
        : results.length ? results.map(item => <View key={item.id} style={[styles.itemRow, { borderColor: colors.border }]}>
          <View style={styles.itemBody}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>{item.title}</Text>
            <Text style={[styles.copy, { color: colors.textMuted }]}>{item.mediaType}</Text>
          </View>
          <Button label={labels.exclude} tone="surface" busy={busyId === item.id}
            disabled={Boolean(busyId)} onPress={() => onExclude?.(item)} palette={buttons} />
        </View>) : <Text style={[styles.copy, { color: colors.textMuted }]}>{query ? labels.noResults : labels.emptySearch}</Text>}
    </View>
    <Text style={[styles.sectionTitle, { color: colors.text }]}>Currently excluded</Text>
    {excluded.length ? excluded.map(item => <View key={item.id} style={[styles.itemRow, { borderColor: colors.border }]}>
      <View style={styles.itemBody}>
        <Text style={[styles.rowTitle, { color: colors.text }]}>{item.title}</Text>
        <Text style={[styles.copy, { color: colors.textMuted }]}>{item.mediaType}</Text>
      </View>
      <Button label={labels.remove} tone="ghost-danger" busy={busyId === item.id}
        disabled={Boolean(busyId)} onPress={() => onInclude?.(item)} palette={buttons} />
    </View>) : <View style={[styles.empty, { borderColor: colors.border }]}>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.noExcluded}</Text>
    </View>}
    {error ? <Text accessibilityRole="alert" style={[styles.status, { color: colors.danger }]}>{error}</Text> : null}
    {success ? <Text accessibilityLiveRegion="polite" style={[styles.status, { color: colors.success }]}>{success}</Text> : null}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 12, lineHeight: 18 },
  status: { fontSize: 12, lineHeight: 18 },
  field: { gap: 4 },
  label: { fontSize: 12, fontWeight: '600' },
  multiline: { borderWidth: 1, borderRadius: 8, minHeight: 110, paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, textAlignVertical: 'top' },
  group: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  sectionTitle: { fontSize: 14, fontWeight: '600' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  resultsBox: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 8 },
  searchingRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  itemRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10, borderBottomWidth: 1, paddingVertical: 8 },
  itemBody: { flexShrink: 1, gap: 2 },
  rowTitle: { fontSize: 13, fontWeight: '600' },
  empty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, padding: 12, alignItems: 'center' },
});
