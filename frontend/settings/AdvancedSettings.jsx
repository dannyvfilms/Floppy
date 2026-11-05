import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';
import { ConfirmDialog } from './ConfirmDialog';
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

const defaultCacheCopy = {
  search: {
    title: 'Clear Search Cache?',
    message: 'This is the one shared cache here — clearing it affects every user on this Floppy instance, not just you.',
    warning: 'No data is lost. The next search anyone makes will be a bit slower while it re-fetches from TMDB, TVDB, and the other providers.',
  },
  history: {
    title: 'Clear History Cache?',
    message: 'Only affects your own account. Your watch history itself is not touched — this only clears the cached, day-by-day rendering of it.',
    warning: 'The History page will rebuild itself the next time you open it, which may take a moment the first time.',
  },
  statistics: {
    title: 'Clear Statistics Cache?',
    message: 'Only affects your own account. No underlying data is touched — only the cached charts and totals.',
    warning: 'Statistics rebuild in the background rather than on your next page load — expect placeholder values for a bit until that finishes.',
  },
  discover: {
    title: 'Clear Discover Cache?',
    message: 'Only affects your own account. Your recommendation rows and taste profile get recomputed from scratch.',
    warning: 'Rows may look different or take a moment to repopulate. Shared provider data other users draw on is not affected.',
  },
  all: {
    title: 'Clear All Caches?',
    message: 'This runs all four clears at once: Search (instance-wide) plus your History, Statistics, and Discover caches.',
    warning: 'Search results go stale for every user until re-fetched. History and Discover rebuild as you browse, and Statistics shows placeholders until a background task finishes. No watch history, ratings, lists, or tracked media is deleted.',
  },
};

const defaultCacheRows = [
  { key: 'search', title: 'Search Cache', description: 'Provider search results — shared instance-wide' },
  { key: 'history', title: 'History Cache', description: 'Your cached History page — just you' },
  { key: 'statistics', title: 'Statistics Cache', description: 'Your cached Statistics page — just you' },
  { key: 'discover', title: 'Discover Cache', description: 'Your recommendation rows and taste profile — just you' },
];

const defaultCacheConfirms = Object.fromEntries(
  Object.entries(defaultCacheCopy).map(([key, value]) => [key, {
    ...value,
    confirmLabel: key === 'all'
      ? 'Clear All Caches'
      : `Clear ${key.charAt(0).toUpperCase()}${key.slice(1)} Cache`,
  }]),
);

const defaultLabels = {
  working: 'Working…',
  logs: {
    title: 'Logs & Bug Reports',
    intro: 'Logs may contain private activity. Administrators can download redacted logs and should review them before sharing.',
    covers: 'Covers {when} onward.',
    lastUnclean: 'Last unclean shutdown: {when}',
    download: 'Download Sanitized Logs',
    bugReport: 'File a Bug Report',
  },
  imageCache: {
    title: 'External Image Caching',
    intro: 'Proxy artwork from approved metadata providers through Floppy so browsers and API clients do not need direct access to those providers. Cached images use disk space and are removed automatically after 30 days without access.',
    cachedImages: 'Cached images',
    diskUsage: 'Disk usage',
    hosts: 'Only known provider image hosts are cached (including TMDB, TVDB, MyAnimeList, IGDB, Open Library, Hardcover, ComicVine, BoardGameGeek, MusicBrainz, Pocket Casts, iTunes, Kitsu, and AniList). Manual URLs, local services, placeholders, and unknown hosts stay unchanged.',
    toggleLabel: 'Enable external image caching',
    disabled: 'Disabled',
    enabled: 'Enabled',
    save: 'Save',
    clear: 'Clear Image Cache',
    confirmTitle: 'Clear Image Cache?',
    confirmMessage: 'Clear all cached external images? They will be downloaded again if caching remains enabled.',
    confirmWarning: 'Artwork may briefly reload the next time it is requested.',
    confirmLabel: 'Clear Image Cache',
    clearError: 'Could not clear the image cache.',
    saveError: 'Could not update image caching.',
    superuserOnly: 'Only a superuser can change this setting or clear the cache.',
    status: 'Status:',
  },
  cache: {
    title: 'Cache Management',
    intro: 'Floppy caches computed pages (History, Statistics, Discover) and provider search results so they load fast. If one looks stale or wrong, clearing it forces a rebuild from your actual data — nothing about your library, watch history, ratings, or lists is touched by any of these.',
    clear: 'Clear',
    clearAll: 'Clear All Caches',
    clearing: '{kind} cache is clearing…',
    confirmError: 'Could not clear that cache.',
    rows: defaultCacheRows,
    confirms: defaultCacheConfirms,
  },
  serverPort: {
    title: 'Server port',
    introManage: 'Change the public HTTP port only when another process in the same network namespace already uses port 8000. A normal Docker host-port change does not need this setting.',
    introReadOnly: 'This status is read-only for your account. An instance administrator can change the saved listener.',
    runningListener: 'Running listener',
    configuredPort: 'Configured port',
    notReported: 'Not reported',
    unavailable: 'Unavailable',
    savedFallback: 'Saved fallback',
    runningHelp: 'Listener reported by the current packaged launcher.',
    configuredHelp: 'Source: {source}',
    configuredUnavailable: 'Correct the active configuration before restart.',
    unreadable: 'Unreadable',
    notEvaluated: 'Not evaluated',
    unreadableHelp: 'Repair or reset the saved value before it can be used.',
    notEvaluatedHelp: 'Correct the environment value before evaluating fallbacks.',
    storedHelp: 'Stored under the Floppy data directory.',
    defaultHelp: 'No saved override. The default is {port}.',
    environmentTitle: 'Environment override is active',
    environmentBody: 'controls this instance. This form cannot replace it. Change or remove the environment variable, then restart Floppy.',
    configEnvironmentTitle: 'Environment server port is invalid',
    configSavedTitle: 'Saved server port cannot be read',
    configAdminTitle: 'Server port configuration needs administrator attention',
    configAdminBody: 'Detailed configuration errors and recovery controls are hidden for this account.',
    configEnvironmentHelp: 'Correct {name} before you restart Floppy.',
    configSavedHelp: 'Reset the saved value below, or correct the file before you restart Floppy.',
    formTitle: 'Internal listener',
    formHelp: 'Use an integer from 1 through 65535. Saving changes the next listener value. It does not restart Floppy.',
    portLabel: 'Port',
    portHelp: 'Priority: {name}, then the saved value, then {port}.',
    save: 'Save port',
    reset: 'Reset saved value',
    invalidPort: 'Use an integer from 1 through 65535.',
    readOnlyNote: 'Need to change the internal listener? Ask an instance administrator, or use the documented environment or CLI configuration for the host.',
    notesTitle: 'Deployment notes',
    notes: [
      '• For a normal host-port change, keep Floppy on 8000 and map another host port, for example 9000:8000.',
      '• If the internal listener must move, use the same target in the container mapping, for example 9000:9000.',
      '• If Floppy shares another container\'s network namespace, publish the selected port on the container that owns that namespace.',
      '• The private application hop remains internal and is not changed by this setting.',
    ],
  },
};

function format(template, values) {
  return String(template || '').replace(/\{(\w+)\}/g, (match, key) =>
    values[key] === undefined ? match : String(values[key]));
}

function mergeLabels(defaults, labels) {
  return { ...defaults, ...(labels || {}) };
}

function StatusLine({ busy, error, success, palette, working = 'Working…' }) {
  if (!busy && !error && !success) return null;
  const color = error ? palette.danger : success ? palette.success : palette.textMuted;
  return <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite"
    style={[styles.status, { color }]}>{error || success || (typeof busy === 'string' ? busy : working)}</Text>;
}

function Stat({ label, value, help, palette }) {
  return <View style={[styles.stat, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
    <Text style={[styles.statLabel, { color: palette.textMuted }]}>{label}</Text>
    <Text style={[styles.statValue, { color: palette.text }]}>{value}</Text>
    {help ? <Text style={[styles.statHelp, { color: palette.textMuted }]}>{help}</Text> : null}
  </View>;
}

export function LogsCard({
  isSuperuser = false,
  logsSince,
  lastUncleanExit,
  bugReportUrl,
  busy = false,
  error,
  success,
  onDownloadLogs,
  onOpenUrl,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = mergeLabels(defaultLabels.logs, labels);
  return <SettingsCard title={copy.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.intro}</Text>
    {logsSince || lastUncleanExit ? <Text style={[styles.meta, { color: colors.textMuted }]}>
      {logsSince ? format(copy.covers, { when: logsSince }) : ''}
      {lastUncleanExit ? `${logsSince ? ' ' : ''}${format(copy.lastUnclean, { when: lastUncleanExit })}` : ''}
    </Text> : null}
    <View style={styles.actions}>
      {isSuperuser ? <Button label={copy.download} busy={busy}
        onPress={onDownloadLogs} palette={buttons} /> : null}
      <Button label={copy.bugReport} tone="surface" disabled={!onOpenUrl}
        onPress={() => onOpenUrl?.(bugReportUrl)} palette={buttons} />
    </View>
    <StatusLine busy={busy} error={error} success={success} palette={colors}
      working={defaultLabels.working} />
  </SettingsCard>;
}

export function ImageCacheCard({
  isSuperuser = false,
  enabled = false,
  count = 0,
  size = '0 B',
  busy = false,
  error,
  success,
  onSave,
  onClear,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = mergeLabels(defaultLabels.imageCache, labels);
  const [draft, setDraft] = useState(Boolean(enabled));
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');

  async function clear() {
    setConfirmError('');
    try {
      await onClear?.();
      setConfirming(false);
    } catch (failure) {
      setConfirmError(failure?.message || copy.clearError);
    }
  }

  return <SettingsCard title={copy.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.intro}</Text>
    <View style={styles.statGrid}>
      <Stat label={copy.cachedImages} value={String(count)} palette={colors} />
      <Stat label={copy.diskUsage} value={size} palette={colors} />
    </View>
    <Text style={[styles.note, { color: colors.textMuted }]}>{copy.hosts}</Text>
    {isSuperuser ? <>
      <ToggleChip label={copy.toggleLabel} value={draft}
        offLabel={copy.disabled} onLabel={copy.enabled} palette={colors}
        onChange={setDraft} />
      <View style={styles.actions}>
        <Button label={copy.save} busy={busy} disabled={draft === Boolean(enabled)}
          onPress={() => onSave?.(draft)} palette={buttons} />
        <Button label={copy.clear} tone="ghost-danger"
          onPress={() => { setConfirmError(''); setConfirming(true); }} palette={buttons} />
      </View>
      <ConfirmDialog visible={confirming} title={copy.confirmTitle}
        message={copy.confirmMessage}
        warning={copy.confirmWarning}
        confirmLabel={copy.confirmLabel} busy={busy} error={confirmError}
        palette={colors} buttonPalette={buttons}
        onCancel={() => setConfirming(false)} onConfirm={clear} />
    </> : <>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.superuserOnly}</Text>
      <Text style={[styles.copy, { color: colors.text }]}>{copy.status} <Text style={styles.strong}>{enabled ? copy.enabled : copy.disabled}</Text></Text>
    </>}
    <StatusLine busy={busy} error={error} success={success} palette={colors}
      working={defaultLabels.working} />
  </SettingsCard>;
}

function CacheRow({ title, description, clearLabel, onPress, palette }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={title}
    accessibilityHint={description} onPress={onPress}
    style={({ pressed }) => [styles.cacheRow, {
      backgroundColor: palette.surfaceStrong, borderColor: palette.border,
    }, pressed && { opacity: 0.75 }]}>
    <View style={styles.cacheCopy}>
      <Text style={[styles.rowTitle, { color: palette.text }]}>{title}</Text>
      <Text style={[styles.rowCopy, { color: palette.textMuted }]}>{description}</Text>
    </View>
    <Text style={[styles.rowAction, { color: palette.textMuted }]}>{clearLabel}</Text>
  </Pressable>;
}

export function CacheManagementCard({
  busyKind = '',
  error,
  success,
  onClear,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = mergeLabels(defaultLabels.cache, labels);
  const [pending, setPending] = useState('');
  const [confirmError, setConfirmError] = useState('');
  const confirmCopy = (copy.confirms || defaultLabels.cache.confirms)[pending]
    || defaultLabels.cache.confirms.all;

  async function confirm() {
    setConfirmError('');
    try {
      await onClear?.(pending);
      setPending('');
    } catch (failure) {
      setConfirmError(failure?.message || copy.confirmError);
    }
  }

  return <SettingsCard title={copy.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.intro}</Text>
    <View style={styles.column}>
      {(copy.rows || defaultLabels.cache.rows).map(row => <CacheRow key={row.key}
        title={row.title} description={row.description} clearLabel={copy.clear}
        onPress={() => { setConfirmError(''); setPending(row.key); }} palette={colors} />)}
    </View>
    <View style={[styles.divider, { borderColor: colors.border }]}>
      <Button label={copy.clearAll} tone="danger-solid"
        onPress={() => { setConfirmError(''); setPending('all'); }} palette={buttons} />
    </View>
    <StatusLine busy={busyKind ? format(copy.clearing, { kind: busyKind }) : ''}
      error={error} success={success} palette={colors} working={defaultLabels.working} />
    <ConfirmDialog visible={Boolean(pending)} title={confirmCopy.title} message={confirmCopy.message}
      warning={confirmCopy.warning} confirmLabel={confirmCopy.confirmLabel}
      busy={Boolean(busyKind)} error={confirmError} palette={colors} buttonPalette={buttons}
      onCancel={() => setPending('')} onConfirm={confirm} />
  </SettingsCard>;
}

export function ServerPortCard({
  canManage = false,
  runtimePort,
  configuredPort,
  configuredSource,
  savedPort,
  defaultPort = 8000,
  savedFallbackUnreadable = false,
  environmentOverride = false,
  environmentName = 'FLOPPY_PORT',
  configError,
  configErrorPresent = false,
  configErrorSource = '',
  showReset = false,
  busy = false,
  error,
  success,
  onSave,
  onReset,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = mergeLabels(defaultLabels.serverPort, labels);
  const initial = savedPort ?? configuredPort ?? defaultPort;
  const [port, setPort] = useState(String(initial));
  const [formError, setFormError] = useState('');

  useEffect(() => {
    setPort(String(savedPort ?? configuredPort ?? defaultPort));
    setFormError('');
  }, [savedPort, configuredPort, defaultPort]);

  function save() {
    const value = Number(port);
    if (!Number.isInteger(value) || value < 1 || value > 65535) {
      setFormError(copy.invalidPort);
      return;
    }
    setFormError('');
    onSave?.(value);
  }

  const savedLabel = savedFallbackUnreadable ? copy.unreadable
    : configErrorSource === 'environment' ? copy.notEvaluated
      : savedPort ? String(savedPort) : String(defaultPort);

  return <SettingsCard title={copy.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{canManage
      ? copy.introManage
      : copy.introReadOnly}</Text>
    <View style={styles.statGrid}>
      <Stat label={copy.runningListener} value={runtimePort ? String(runtimePort) : copy.notReported}
        help={copy.runningHelp} palette={colors} />
      <Stat label={copy.configuredPort} value={configuredPort ? String(configuredPort) : copy.unavailable}
        help={configuredPort ? format(copy.configuredHelp, { source: configuredSource || 'default' }) : copy.configuredUnavailable}
        palette={colors} />
      {canManage ? <Stat label={copy.savedFallback} value={savedLabel}
        help={savedFallbackUnreadable ? copy.unreadableHelp
          : configErrorSource === 'environment' ? copy.notEvaluatedHelp
            : savedPort ? copy.storedHelp
              : format(copy.defaultHelp, { port: defaultPort })}
        palette={colors} /> : null}
    </View>
    {environmentOverride ? <View style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.noticeTitle, { color: colors.warning }]}>{copy.environmentTitle}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}><Text style={styles.mono}>{environmentName}</Text> {copy.environmentBody}</Text>
    </View> : null}
    {configError || configErrorPresent ? <View accessibilityRole="alert" style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.danger }]}>
      <Text style={[styles.noticeTitle, { color: colors.danger }]}>{canManage
        ? configErrorSource === 'environment' ? copy.configEnvironmentTitle : copy.configSavedTitle
        : copy.configAdminTitle}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{canManage
        ? configError
        : copy.configAdminBody}</Text>
      {canManage ? <Text style={[styles.copy, { color: colors.textMuted }]}>{configErrorSource === 'environment'
        ? format(copy.configEnvironmentHelp, { name: environmentName })
        : copy.configSavedHelp}</Text> : null}
    </View> : null}
    {canManage ? <View style={[styles.form, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>{copy.formTitle}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.formHelp}</Text>
      <TextField label={copy.portLabel} name="port" type="number" value={port}
        disabled={environmentOverride || busy} error={formError}
        help={format(copy.portHelp, { name: environmentName, port: defaultPort })}
        palette={colors} onChangeText={setPort} />
      <View style={styles.actions}>
        <Button label={copy.save} busy={busy} disabled={environmentOverride || busy}
          onPress={save} palette={buttons} />
        {showReset ? <Button label={copy.reset} tone="surface" disabled={busy}
          onPress={onReset} palette={buttons} /> : null}
      </View>
    </View> : <View style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.readOnlyNote}</Text>
    </View>}
    <StatusLine busy={busy} error={error} success={success} palette={colors}
      working={defaultLabels.working} />
    <View style={styles.notes}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>{copy.notesTitle}</Text>
      {(copy.notes || defaultLabels.serverPort.notes).map(note => <Text key={note}
        style={[styles.bullet, { color: colors.textMuted }]}>{note}</Text>)}
    </View>
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 13, lineHeight: 19 },
  note: { fontSize: 12, lineHeight: 17 },
  meta: { fontSize: 12, lineHeight: 17 },
  status: { fontSize: 12, lineHeight: 17 },
  strong: { fontWeight: '600' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  stat: { flexGrow: 1, flexBasis: '45%', borderWidth: 1, borderRadius: 8, padding: 12, gap: 2 },
  statLabel: { fontSize: 11, letterSpacing: 0.4, textTransform: 'uppercase' },
  statValue: { fontSize: 18, fontWeight: '600' },
  statHelp: { fontSize: 11, lineHeight: 16 },
  column: { gap: 8 },
  cacheRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, borderWidth: 1, borderRadius: 8, padding: 12 },
  cacheCopy: { flexShrink: 1, gap: 2 },
  rowTitle: { fontSize: 14, fontWeight: '600' },
  rowCopy: { fontSize: 12, lineHeight: 17 },
  rowAction: { fontSize: 12, fontWeight: '600' },
  divider: { borderTopWidth: 1, paddingTop: 12 },
  notice: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 6 },
  noticeTitle: { fontSize: 13, fontWeight: '700' },
  mono: { fontFamily: 'Courier' },
  form: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  notes: { gap: 4 },
  bullet: { fontSize: 12, lineHeight: 18 },
});
