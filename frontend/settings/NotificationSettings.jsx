import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Icon } from '../ui/Icon';
import { actionIcons } from '../ui/actionIcons';
import { ArtworkImage } from '../ui/ArtworkImage';
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

function MultiLineField({ id, label, labelHidden, help, value, placeholder, disabled, palette, onChangeText }) {
  return <View style={styles.field}>
    {!labelHidden ? <Text nativeID={id ? `${id}-label` : undefined} style={[styles.label, { color: palette.textMuted }]}>{label}</Text> : null}
    {help && !palette.pageCards ? <Text style={[styles.copy, { color: palette.textMuted }]}>{help}</Text> : null}
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
        ...(palette.pageCards ? { minHeight: 150, fontSize: 14, borderRadius: 6 } : {}),
        backgroundColor: palette.pageCards ? palette.surfaceStrong : palette.surface,
        borderColor: palette.border,
        color: palette.textSecondary,
        opacity: disabled ? 0.5 : 1,
      }]}
    />
    {help && palette.pageCards ? <Text style={[styles.copy, { color: palette.textMuted }]}>{help}</Text> : null}
  </View>;
}

export function NotificationPreferencesCard({
  icon,
  testIcon,
  onOpenLink,
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
  const [showInfo, setShowInfo] = useState(false);
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

  return <SettingsCard title={labels.title} icon={icon} palette={colors}>
    <Text style={[styles.copy, colors.pageCards && { fontSize: 14, lineHeight: 20, marginBottom: 4 }, { color: colors.textMuted }]}>{labels.description}</Text>
    {colors.pageCards ? <View style={{ gap: 12, marginBottom: -8 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={{ fontSize: 14, fontWeight: '500', color: colors.textSecondary }}>{labels.apprise}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="About Apprise URLs" accessibilityState={{ expanded: showInfo }}
          onPress={() => setShowInfo(value => !value)} hitSlop={8}>
          <Icon spec={actionIcons.info} color={colors.textMuted} size={16} />
        </Pressable>
      </View>
      {showInfo ? <View style={{ padding: 12, borderRadius: 6, backgroundColor: colors.surfaceStrong, gap: 8 }}>
        <Text style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 20 }}>
          <Text accessibilityRole="link" onPress={() => onOpenLink?.('https://github.com/caronc/apprise')} style={{ color: colors.link }}>Apprise</Text>
          {' is a notification service that supports '}
          <Text accessibilityRole="link" onPress={() => onOpenLink?.('https://github.com/caronc/apprise/wiki')} style={{ color: colors.link }}>many platforms</Text>
          {' including:'}
        </Text>
        {['Discord', 'Notifiarr', 'Telegram', 'Slack', 'Email', 'Pushover', 'ntfy', 'And many more...'].map(platform => <Text key={platform} style={{ color: colors.textMuted, fontSize: 14, lineHeight: 20 }}>{`• ${platform}`}</Text>)}
        <Text style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 20 }}>Enter one URL per line. Examples: discord://webhook_id/webhook_token or notifiarr://api_key/#channel_id</Text>
      </View> : null}
    </View> : null}
    <MultiLineField id="notification-urls" label={labels.apprise} labelHidden={colors.pageCards} help={savedDescription}
      value={values.notificationUrls} placeholder={labels.apprisePlaceholder}
      disabled={busy} palette={colors} onChangeText={value => update({ notificationUrls: value })} />
    {colors.pageCards ? <Text style={[styles.sectionTitle, { color: colors.textSecondary }]}>{labels.playbackWebhook}</Text> : null}
    <View style={[styles.group, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 16, gap: 4 }]}>
      {!colors.pageCards ? <>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.playbackWebhook}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.playbackWebhookHelp}</Text>
      </> : null}
      <TextField label={labels.playbackWebhookUrl} name="playback_webhook_url" type="url"
        labelHidden={colors.pageCards} help={colors.pageCards ? labels.playbackWebhookHelp : undefined} helpAfter={colors.pageCards}
        value={values.playbackWebhookUrl} placeholder={stored.playbackWebhookUrl ? 'Leave blank to keep the saved URL' : 'https://example.com/playback'}
        disabled={busy} palette={colors} onChangeText={value => update({ playbackWebhookUrl: value })} />
      <TextField label={labels.playbackWebhookSecret} name="playback_webhook_secret" type="password"
        labelHidden={colors.pageCards} helpAfter={colors.pageCards}
        value={values.playbackWebhookSecret} maskedPreview={stored.playbackWebhookSecret ? '••••••••' : undefined}
        placeholder={stored.playbackWebhookSecret || colors.pageCards ? 'Leave blank to keep the current secret' : 'Optional shared secret'}
        help={labels.secretHelp} disabled={busy} palette={colors}
        onChangeText={value => update({ playbackWebhookSecret: value })} />
    </View>
    {colors.pageCards ? <Text style={[styles.sectionTitle, { color: colors.textSecondary }]}>{labels.settings}</Text> : null}
    <View style={[styles.group, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 16, gap: 16 }]}>
      {!colors.pageCards ? <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.settings}</Text> : null}
      <ToggleChip label={labels.dailyDigest} help={labels.dailyDigestHelp} value={Boolean(values.dailyDigestEnabled)}
        icon={model.icons?.dailyDigest}
        offLabel="Off" onLabel="On" palette={colors} disabled={busy}
        onChange={value => update({ dailyDigestEnabled: value })} />
      <ToggleChip label={labels.releaseNotifications} help={labels.releaseNotificationsHelp}
        icon={model.icons?.releaseNotifications}
        value={Boolean(values.releaseNotificationsEnabled)} offLabel="Off" onLabel="On"
        palette={colors} disabled={busy} onChange={value => update({ releaseNotificationsEnabled: value })} />
      <ToggleChip label={labels.premiereNotifications} help={labels.premiereNotificationsHelp}
        icon={model.icons?.premiereNotifications}
        value={Boolean(values.premiereNotificationsEnabled)} offLabel="Off" onLabel="On"
        palette={colors} disabled={busy} onChange={value => update({ premiereNotificationsEnabled: value })} />
    </View>
    {success ? <Text accessibilityLiveRegion="polite" style={[styles.status, { color: colors.success }]}>{success}</Text> : null}
    {error && colors.pageCards ? <Text accessibilityRole="alert" style={[styles.status, { color: colors.danger }]}>{error}</Text> : null}
    <View style={[styles.actions, colors.pageCards && { justifyContent: 'space-between', borderTopWidth: 1, borderColor: colors.border, paddingTop: 16 }]}>
      <Button label={testing ? labels.testing : labels.test} tone="surface" busy={testing} icon={testIcon}
        disabled={testing || busy} onPress={test} palette={buttons} />
      {colors.pageCards ? <Button label={labels.save} busy={busy && !testing} disabled={busy} onPress={onSave} palette={buttons} /> : null}
    </View>
    {!colors.pageCards ? <FormSaveBar dirty={dirty} saving={busy && !testing} error={error} onSave={onSave} saveLabel={labels.save}
      labels={{
        savedTitle: labels.savedTitle,
        dirtyTitle: labels.dirtyTitle,
        dirtyCopy: labels.dirtyCopy,
        savingCopy: labels.savingCopy,
        errorTitle: labels.errorTitle,
        save: labels.save,
        saving: 'Saving…',
      }}
      palette={colors} buttonPalette={buttons} /> : null}
  </SettingsCard>;
}

export function ExcludedMediaCard({
  icon,
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

  return <SettingsCard title={labels.excludedTitle} icon={icon} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.excludedDescription}</Text>
    <TextField label={labels.search} labelHidden name="notification_search" value={query}
      placeholder={labels.searchPlaceholder} palette={colors}
      onChangeText={value => onSearchChange?.(value)} />
    {query || !colors.pageCards ? <View style={[styles.resultsBox, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      {model.searching ? <View style={styles.searchingRow}><Spinner size={16} color={colors.accent} />
        <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.searching}</Text></View>
        : results.length ? results.map(item => <View key={item.id} style={[styles.itemRow, { borderColor: colors.border }]}>
          {colors.pageCards ? <ArtworkImage src={item.image} title={item.title} style={{ width: 32, height: 40, borderRadius: 4 }} /> : null}
          <View style={styles.itemBody}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>{item.title}</Text>
            <Text style={[styles.copy, { color: colors.textMuted }]}>{item.mediaType}</Text>
          </View>
          <Button label={labels.exclude} tone="surface" busy={busyId === item.id}
            disabled={Boolean(busyId)} onPress={() => onExclude?.(item)} palette={buttons} />
        </View>) : <Text style={[styles.copy, { color: colors.textMuted }]}>{query ? labels.noResults : labels.emptySearch}</Text>}
    </View> : null}
    <Text style={[styles.sectionTitle, { color: colors.text }]}>{colors.pageCards ? 'Currently Excluded:' : 'Currently excluded'}</Text>
    {excluded.length ? excluded.map(item => <View key={item.id} style={[styles.itemRow, { borderColor: colors.border }, colors.pageCards && { backgroundColor: colors.surfaceStrong, borderBottomWidth: 0, borderRadius: 6, padding: 8, gap: 8 }]}>
      {colors.pageCards ? <ArtworkImage src={item.image} title={item.title} style={{ width: 32, height: 40, borderRadius: 4 }} /> : null}
      <View style={[styles.itemBody, colors.pageCards && { flex: 1 }]}>
        <Text style={[styles.rowTitle, { color: colors.text }]}>{item.title}</Text>
        <Text style={[styles.copy, { color: colors.textMuted }]}>{item.mediaType}</Text>
      </View>
      {colors.pageCards ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.remove}: ${item.title}`}
        disabled={Boolean(busyId)} onPress={() => onInclude?.(item)} hitSlop={8} style={{ marginRight: 8 }}>
        <Icon spec={actionIcons.close} color={colors.dangerText || colors.danger} size={16} />
      </Pressable> : <Button label={labels.remove} tone="ghost-danger" busy={busyId === item.id}
        disabled={Boolean(busyId)} onPress={() => onInclude?.(item)} palette={buttons} />}
    </View>) : <View style={[styles.empty, { borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 8, backgroundColor: colors.surfaceStrong, borderRadius: 6 }]}>
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
