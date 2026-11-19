import React, { useEffect, useState } from 'react';
import {
  Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';
import { ConfirmDialog } from './ConfirmDialog';

const defaultPalette = {
  background: '#18181b',
  pageBackground: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  link: '#818cf8',
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
    message: 'This is the one shared cache here. Clearing it affects every user on this Floppy instance, not just you.',
    warning: 'No data is lost. The next search anyone makes will be a bit slower while it re-fetches from TMDB, TVDB, and the other providers.',
  },
  history: {
    title: 'Clear History Cache?',
    message: 'Only affects your own account. Your watch history itself is not touched. This only clears the cached, day-by-day rendering of it.',
    warning: 'The History page will rebuild itself the next time you open it, which may take a moment the first time.',
  },
  statistics: {
    title: 'Clear Statistics Cache?',
    message: 'Only affects your own account. No underlying data is touched, only the cached charts and totals.',
    warning: 'Statistics rebuild in the background rather than on your next page load. Expect placeholder values for a bit until that finishes.',
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
  { key: 'search', title: 'Search Cache', description: 'Provider search results (shared instance-wide)' },
  { key: 'history', title: 'History Cache', description: 'Your cached History page (just you)' },
  { key: 'statistics', title: 'Statistics Cache', description: 'Your cached Statistics page (just you)' },
  { key: 'discover', title: 'Discover Cache', description: 'Your recommendation rows & taste profile (just you)' },
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
    intro: 'Logs may contain private activity. Administrators can download redacted logs and should review them before sharing. Everyone can download a diagnostic report with only server details and recent warnings and errors.',
    covers: 'Covers {when} onward.',
    lastUnclean: 'Last unclean shutdown: {when}',
    download: 'Download Sanitized Logs',
    downloadDiagnostics: 'Download Diagnostic Report',
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
    intro: 'Floppy caches computed pages (History, Statistics, Discover) and provider search results so they load fast. If one looks stale or wrong, clearing it forces a rebuild from your actual data. Nothing about your library, watch history, ratings, or lists is touched by any of these.',
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

function useColors(palette) {
  return { ...defaultPalette, ...palette, link: palette?.link || palette?.accent || defaultPalette.link };
}

function Panel({ colors, headingIcon, title, children, titleSize = 16, style }) {
  return <View style={[styles.panel, {
    backgroundColor: colors.surfaceStrong, borderRadius: colors.radius,
  }, style]}>
    <View style={[styles.panelHeading, titleSize === 20 && styles.panelHeadingLarge]}>
      {headingIcon ? <View style={[styles.panelIcon, { fontSize: titleSize === 20 ? 24 : 20, color: colors.link }]}>
        <Icon spec={headingIcon} />
      </View> : null}
      <Text role="heading" aria-level={titleSize === 20 ? 2 : 3}
        style={[styles.panelTitle, { color: colors.text, fontSize: titleSize, lineHeight: titleSize === 20 ? 28 : 24 }]}>
        {title}
      </Text>
    </View>
    {children}
  </View>;
}

function StatusLine({ busy, error, success, colors, working = 'Working…' }) {
  if (!busy && !error && !success) return null;
  const color = error ? colors.danger : success ? colors.success : colors.textMuted;
  return <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite"
    style={[styles.status, { color }]}>{error || success || (typeof busy === 'string' ? busy : working)}</Text>;
}

function Stat({ label, value, help, colors, compact = false, large = false }) {
  return <View style={[styles.stat, compact && styles.statCompact, { backgroundColor: colors.surface, borderColor: colors.border, borderRadius: colors.radius }]}>
    <Text style={[styles.statLabel, { color: colors.textMuted }]}>{label}</Text>
    <Text style={[styles.statValue, compact && styles.statValueCompact, large && styles.statValueLarge, { color: colors.text }]}>{value}</Text>
    {help ? <Text style={[styles.statHelp, { color: colors.textMuted }]}>{help}</Text> : null}
  </View>;
}

function DangerTintButton({ label, onPress, colors, icon }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    onPress={onPress} style={({ pressed }) => [styles.dangerTint, {
      backgroundColor: 'rgba(220, 38, 38, 0.1)', borderColor: 'rgba(220, 38, 38, 0.4)',
      borderRadius: colors.radius,
    }, pressed && { backgroundColor: 'rgba(220, 38, 38, 0.2)' }]}>
    {icon ? <View style={[styles.tinyIcon, { fontSize: 16, color: colors.danger }]}><Icon spec={icon} /></View> : null}
    <Text style={[styles.dangerTintText, { color: colors.danger }]}>{label}</Text>
  </Pressable>;
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
  onDownloadDiagnostics,
  onOpenUrl,
  palette = {},
  buttonPalette = {},
  labels = {},
  icons = {},
}) {
  const colors = useColors(palette);
  const buttons = { ...defaultButtonPalette, ...buttonPalette, radius: buttonPalette.radius ?? colors.radius ?? defaultButtonPalette.radius };
  const copy = mergeLabels(defaultLabels.logs, labels);
  return <Panel colors={colors} headingIcon={icons.logs} title={copy.title}>
    <Text style={[styles.copy, styles.logsIntro, { color: colors.textMuted }]}>{copy.intro}
      {logsSince || lastUncleanExit ? <>
        {'\n'}
        {logsSince ? format(copy.covers, { when: logsSince }) : ''}
        {lastUncleanExit ? `${logsSince ? ' ' : ''}${format(copy.lastUnclean, { when: lastUncleanExit })}` : ''}
      </> : null}
    </Text>
    <View style={styles.actions}>
      {isSuperuser ? <Button label={copy.download} busy={busy} icon={icons.download}
        onPress={onDownloadLogs} palette={buttons} width="auto" /> : null}
      {onDownloadDiagnostics ? <Button label={copy.downloadDiagnostics} busy={busy}
        icon={icons.download} tone={isSuperuser ? 'surface' : undefined}
        onPress={onDownloadDiagnostics} palette={buttons} width="auto" /> : null}
      <Button label={copy.bugReport} tone="surface" disabled={!onOpenUrl}
        onPress={() => onOpenUrl?.(bugReportUrl)} palette={buttons} width="auto" />
    </View>
    <StatusLine busy={busy} error={error} success={success} colors={colors}
      working={defaultLabels.working} />
  </Panel>;
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
  icons = {},
}) {
  const colors = useColors(palette);
  const buttons = { ...defaultButtonPalette, ...buttonPalette, radius: buttonPalette.radius ?? colors.radius ?? defaultButtonPalette.radius };
  const copy = mergeLabels(defaultLabels.imageCache, labels);
  const { width } = useWindowDimensions();
  const [draft, setDraft] = useState(Boolean(enabled));
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  const twoColumns = width >= 640;

  useEffect(() => {
    setDraft(Boolean(enabled));
  }, [enabled]);

  async function clear() {
    setConfirmError('');
    try {
      await onClear?.();
      setConfirming(false);
    } catch (failure) {
      setConfirmError(failure?.message || copy.clearError);
    }
  }

  return <Panel colors={colors} headingIcon={icons.image} title={copy.title}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.intro}</Text>
    <View style={[styles.statGrid, twoColumns ? styles.statGridTwo : styles.statGridOne]}>
      <Stat label={copy.cachedImages} value={String(count)} colors={colors} compact />
      <Stat label={copy.diskUsage} value={size} colors={colors} compact />
    </View>
    <Text style={[styles.note, { color: colors.textMuted }]}>{copy.hosts}</Text>
    {isSuperuser ? <>
      <View style={styles.actions}>
        <Pressable accessibilityRole="checkbox" accessibilityLabel={copy.toggleLabel}
          aria-checked={draft}
          accessibilityState={{ checked: draft }} onPress={() => setDraft(value => !value)}
          style={({ pressed }) => [styles.checkRow, pressed && styles.pressed]}>
          <View style={[styles.checkbox, { borderColor: colors.border, backgroundColor: colors.surface }]}>
            {draft ? <Text style={[styles.checkboxMark, { color: colors.accentStrong }]}>✓</Text> : null}
          </View>
          <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.toggleLabel}</Text>
        </Pressable>
        <Button label={copy.save} busy={busy} disabled={draft === Boolean(enabled)}
          onPress={() => onSave?.(draft)} palette={buttons} width="auto" />
        <DangerTintButton label={copy.clear} colors={colors}
          onPress={() => { setConfirmError(''); setConfirming(true); }} />
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
    <StatusLine busy={busy} error={error} success={success} colors={colors}
      working={defaultLabels.working} />
  </Panel>;
}

function CacheRow({ title, description, onPress, colors, icon }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={title}
    accessibilityHint={description} onPress={onPress}
    style={({ pressed }) => [styles.cacheRow, {
      backgroundColor: colors.surface, borderColor: colors.border, borderRadius: colors.radius,
    }, pressed && { borderColor: colors.accent }]}>
    <View style={styles.cacheCopy}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{description}</Text>
    </View>
    {icon ? <View style={[styles.rowIcon, { fontSize: 16, color: colors.textMuted }]}>
      <Icon spec={icon} />
    </View> : null}
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
  icons = {},
}) {
  const colors = useColors(palette);
  const buttons = { ...defaultButtonPalette, ...buttonPalette, radius: buttonPalette.radius ?? colors.radius ?? defaultButtonPalette.radius };
  const copy = mergeLabels(defaultLabels.cache, labels);
  const { width } = useWindowDimensions();
  const twoColumns = width >= 640;
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

  return <Panel colors={colors} headingIcon={icons.trash} title={copy.title}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.intro}</Text>
    <View style={[styles.cacheGrid, twoColumns && styles.cacheGridTwo]}>
      {(copy.rows || defaultLabels.cache.rows).map(row => <View key={row.key}
        style={twoColumns ? styles.cacheCell : null}>
        <CacheRow title={row.title} description={row.description}
          icon={icons.trash}
          onPress={() => { setConfirmError(''); setPending(row.key); }} colors={colors} />
      </View>)}
    </View>
    <View style={[styles.divider, { borderColor: colors.border }]}>
      <DangerTintButton label={copy.clearAll} colors={colors} icon={icons.warning}
        onPress={() => { setConfirmError(''); setPending('all'); }} />
    </View>
    <StatusLine busy={busyKind ? format(copy.clearing, { kind: busyKind }) : ''}
      error={error} success={success} colors={colors} working={defaultLabels.working} />
    <ConfirmDialog visible={Boolean(pending)} title={confirmCopy.title} message={confirmCopy.message}
      warning={confirmCopy.warning} confirmLabel={confirmCopy.confirmLabel}
      busy={Boolean(busyKind)} error={confirmError} palette={colors} buttonPalette={buttons}
      onCancel={() => setPending('')} onConfirm={confirm} />
  </Panel>;
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
  icons = {},
}) {
  const colors = useColors(palette);
  const buttons = { ...defaultButtonPalette, ...buttonPalette, radius: buttonPalette.radius ?? colors.radius ?? defaultButtonPalette.radius };
  const copy = mergeLabels(defaultLabels.serverPort, labels);
  const { width } = useWindowDimensions();
  const [port, setPort] = useState(String(savedPort ?? configuredPort ?? defaultPort));
  const [formError, setFormError] = useState('');
  const statColumns = width >= 640 ? (canManage ? 3 : 2) : 1;

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

  return <View style={[styles.portCard, {
    backgroundColor: colors.surface, borderRadius: colors.radius,
  }]}>
    <View style={styles.portHeading}>
      {icons.server ? <View style={[styles.portIcon, { fontSize: 24, color: colors.link }]}>
        <Icon spec={icons.server} />
      </View> : null}
      <Text role="heading" aria-level={2} style={[styles.portTitle, { color: colors.text }]}>{copy.title}</Text>
    </View>
    <Text style={[styles.portIntro, { color: colors.textMuted }]}>{canManage
      ? copy.introManage
      : copy.introReadOnly}</Text>
    <View style={[styles.statGrid, statColumns === 1 ? styles.statGridOne : styles.statGridTwo, styles.portStatGrid]}>
      <Stat label={copy.runningListener} value={runtimePort ? String(runtimePort) : copy.notReported}
        help={copy.runningHelp} colors={colors} large />
      <Stat label={copy.configuredPort} value={configuredPort ? String(configuredPort) : copy.unavailable}
        help={configuredPort ? format(copy.configuredHelp, { source: configuredSource || 'default' }) : copy.configuredUnavailable}
        colors={colors} large />
      {canManage ? <Stat label={copy.savedFallback} value={savedLabel}
        help={savedFallbackUnreadable ? copy.unreadableHelp
          : configErrorSource === 'environment' ? copy.notEvaluatedHelp
            : savedPort ? copy.storedHelp
              : format(copy.defaultHelp, { port: defaultPort })}
        colors={colors} large /> : null}
    </View>
    {environmentOverride ? <View style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.border, borderRadius: colors.radius }]}>
      <Text style={[styles.noticeTitle, { color: colors.warning }]}>{copy.environmentTitle}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>
        <Text style={styles.mono}>{environmentName}</Text> {copy.environmentBody}
      </Text>
    </View> : null}
    {configError || configErrorPresent ? <View accessibilityRole="alert" style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.border, borderRadius: colors.radius }]}>
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
    {canManage ? <View style={[styles.form, { backgroundColor: colors.surfaceStrong, borderRadius: colors.radius }]}>
      <Text style={[styles.formTitle, { color: colors.text }]}>{copy.formTitle}</Text>
      <Text style={[styles.formHelp, { color: colors.textMuted }]}>{copy.formHelp}</Text>
      <View style={styles.field}>
        <Text style={[styles.fieldLabel, { color: colors.text }]}>{copy.portLabel}</Text>
        <TextInput accessibilityLabel={copy.portLabel} aria-describedby="server-port-help server-port-source"
          keyboardType="number-pad" editable={!environmentOverride && !busy} inputMode="numeric"
          onChangeText={setPort} value={port}
          style={[styles.input, {
            borderColor: formError ? colors.danger : colors.border,
            backgroundColor: colors.surface, color: colors.text,
            borderRadius: colors.radius, opacity: environmentOverride ? 0.5 : 1,
          }]} />
        <Text nativeID="server-port-source" style={[styles.fieldHelp, { color: colors.textMuted }]}>
          {format(copy.portHelp, { name: environmentName, port: defaultPort })}
        </Text>
        {formError ? <Text accessibilityRole="alert" style={[styles.fieldHelp, { color: colors.danger }]}>{formError}</Text> : null}
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.save}
        disabled={environmentOverride || busy} onPress={save}
        style={({ pressed }) => [styles.portButton, {
          backgroundColor: colors.link, borderRadius: colors.radius,
          opacity: environmentOverride || busy ? 0.5 : pressed ? 0.9 : 1,
        }]}>
        <Text style={[styles.portButtonText, { color: colors.pageBackground }]}>{copy.save}</Text>
      </Pressable>
      {showReset ? <View style={styles.reset}>
        <Button label={copy.reset} tone="surface" disabled={busy} onPress={onReset}
          palette={buttons} width="auto" />
      </View> : null}
    </View> : <View style={[styles.notice, { backgroundColor: colors.surfaceStrong, borderColor: colors.border, borderRadius: colors.radius }]}>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.readOnlyNote}</Text>
    </View>}
    <StatusLine busy={busy} error={error} success={success} colors={colors}
      working={defaultLabels.working} />
    <View style={styles.notes}>
      <Text style={[styles.notesTitle, { color: colors.text }]}>{copy.notesTitle}</Text>
      <View style={styles.noteList}>
        {(copy.notes || defaultLabels.serverPort.notes).map(note => <Text key={note}
          style={[styles.noteItem, { color: colors.textMuted }]}>{note}</Text>)}
      </View>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  panel: { padding: 20, gap: 0, minWidth: 0 },
  panelHeading: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12 },
  panelHeadingLarge: { marginBottom: 8 },
  panelIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  panelTitle: { fontWeight: '500', flexShrink: 1 },
  copy: { fontSize: 14, lineHeight: 20 },
  note: { fontSize: 12, lineHeight: 16, marginBottom: 16 },
  status: { fontSize: 12, lineHeight: 17, marginTop: 8 },
  strong: { fontWeight: '500' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  logsIntro: { marginBottom: 16 },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 16, marginBottom: 16 },
  statGridTwo: { flexDirection: 'row' },
  statGridOne: { flexDirection: 'column' },
  portStatGrid: { marginTop: 0, marginBottom: 24 },
  stat: { flex: 1, minWidth: 0, padding: 16, gap: 0 },
  statCompact: { paddingVertical: 12, paddingHorizontal: 16 },
  statValueCompact: { marginTop: 0 },
  statValueLarge: { fontSize: 18, lineHeight: 28, fontWeight: '600' },
  statLabel: { fontSize: 12, lineHeight: 16, letterSpacing: 0.4, textTransform: 'uppercase' },
  statValue: { fontSize: 14, lineHeight: 20, fontWeight: '500', marginTop: 4 },
  statHelp: { fontSize: 12, lineHeight: 16, marginTop: 4 },
  checkbox: { width: 16, height: 16, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  checkboxMark: { fontSize: 12, lineHeight: 14, fontWeight: '700' },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 },
  dangerTint: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
  dangerTintText: { fontSize: 14, lineHeight: 20 },
  tinyIcon: { width: 16, height: 16, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.75 },
  cacheGrid: { gap: 12, marginTop: 16 },
  cacheGridTwo: { flexDirection: 'row', flexWrap: 'wrap' },
  cacheCell: { flexBasis: '48%', flexGrow: 1, minWidth: 0 },
  cacheRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, borderWidth: 1, paddingHorizontal: 16, paddingVertical: 12, minWidth: 0 },
  cacheCopy: { flexShrink: 1, gap: 2, minWidth: 0 },
  rowTitle: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  rowCopy: { fontSize: 12, lineHeight: 16 },
  rowIcon: { width: 16, height: 16, alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  divider: { borderTopWidth: 1, paddingTop: 16, marginTop: 16, alignItems: 'flex-start' },
  portCard: { padding: 24, minWidth: 0, marginTop: 24 },
  portHeading: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 8 },
  portIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  portTitle: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
  portIntro: { fontSize: 14, lineHeight: 20, marginBottom: 24, maxWidth: 896 },
  notice: { borderWidth: 1, padding: 16, gap: 4, marginBottom: 24 },
  noticeTitle: { fontSize: 16, lineHeight: 24, fontWeight: '500' },
  mono: { fontFamily: 'Courier', fontSize: 13 },
  form: { padding: 20, gap: 0 },
  formTitle: { fontSize: 16, lineHeight: 24, fontWeight: '500', marginBottom: 4 },
  formHelp: { fontSize: 14, lineHeight: 20, marginBottom: 16 },
  field: { gap: 8, maxWidth: 576 },
  fieldLabel: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  input: { borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8, fontSize: 14, lineHeight: 20 },
  fieldHelp: { fontSize: 12, lineHeight: 16, marginTop: 8 },
  portButton: { alignSelf: 'flex-start', paddingHorizontal: 16, paddingVertical: 8, marginTop: 16 },
  portButtonText: { fontSize: 14, lineHeight: 20 },
  reset: { marginTop: 12, alignSelf: 'flex-start' },
  notes: { marginTop: 20, maxWidth: 896 },
  notesTitle: { fontSize: 16, lineHeight: 24, fontWeight: '500' },
  noteList: { gap: 8, marginTop: 8 },
  noteItem: { fontSize: 14, lineHeight: 20 },
});
