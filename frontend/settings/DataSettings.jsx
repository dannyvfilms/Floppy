import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
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

const defaultLabels = {
  title: 'Export data',
  description: 'Export media, ratings and lists as CSV, or create a recurring export schedule.',
  frequency: 'Export frequency',
  time: 'Export time',
  content: 'Export content',
  contentHelp: 'Keep at least one media type, Custom Lists, or Collection enabled.',
  lists: 'Custom Lists',
  collection: 'Collection',
  submitOnce: 'Export as CSV',
  submitScheduled: 'Export as CSV and Save Schedule',
  submitBusy: 'Preparing export…',
  noneSelected: 'Choose at least one media type, Custom Lists, or Collection.',
  scheduledTitle: 'Active scheduled exports',
  scheduledDescription: 'Automated exports that run until you delete the schedule.',
  scheduledEmpty: 'No scheduled exports configured.',
  deleteSchedule: 'Delete schedule',
  deleteScheduleTitle: 'Delete export schedule?',
  deleteScheduleCopy: 'This stops the recurring CSV export. Files already written stay on the server.',
  historyTitle: 'Export history',
  historyDescription: 'Export activity from the last seven days.',
  historyEmpty: 'No exports in the last seven days.',
  restoreTitle: 'Restore a Floppy backup',
  restoreDescription: 'Restore replaces tracked media, progress and history from a Floppy backup file.',
  restoreWarning: 'Restoring is destructive. Entries created after the backup may be lost.',
  chooseBackup: 'Choose backup file',
  restore: 'Restore backup',
  restoreBusy: 'Restoring…',
  restoreTitleConfirm: 'Restore this backup?',
  restoreCopy: 'Type RESTORE to replace the current library with the selected backup.',
  rssTitle: 'RSS feed',
  rssDescription: 'Turn a Discover row into a feed for Radarr, Sonarr or another RSS reader.',
  mediaType: 'Media type',
  row: 'Row',
  skipPlanning: 'Skip Planning',
  skipCollected: 'Skip Collected',
  feedUrl: 'Feed URL',
  copy: 'Copy',
  preview: 'Preview',
  previewLoading: 'Loading preview…',
  previewEmpty: 'This row has no items to preview.',
  previewReady: 'Feed preview ready.',
  feedHint: 'Regenerating your API token from Access & Tokens invalidates old feed links.',
};

const frequencyOptions = [
  { value: 'once', label: 'Export Once' },
  { value: 'daily', label: 'Every Day' },
  { value: '2days', label: 'Every 2 Days' },
  { value: 'weekly', label: 'Weekly' },
];

const statusTones = {
  SUCCESS: { label: 'Success', color: '#34d399' },
  STARTED: { label: 'Started', color: '#60a5fa' },
  FAILURE: { label: 'Failed', color: '#f87171' },
  PENDING: { label: 'Pending', color: '#fbbf24' },
};

function StatusLine({ busy, error, success, palette }) {
  if (!busy && !error && !success) return null;
  const color = error ? palette.danger : success ? palette.success : palette.textMuted;
  return <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite"
    style={[styles.status, { color }]}>{error || success || (typeof busy === 'string' ? busy : 'Working…')}</Text>;
}

function Meta({ label, value, palette }) {
  return <View style={styles.metaRow}>
    <Text style={[styles.metaLabel, { color: palette.textMuted }]}>{label}</Text>
    <Text style={[styles.metaValue, { color: palette.textSecondary }]}>{value}</Text>
  </View>;
}

export function ExportScheduleCard({
  model = {},
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onChange,
  onSubmit,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const selected = model.selectedMediaTypes || [];
  const options = model.frequencyOptions || frequencyOptions;
  const scheduled = model.frequency && model.frequency !== 'once';
  const hasContent = selected.length > 0 || model.includeLists || model.includeCollection;
  const update = changes => onChange?.({ ...model, ...changes });

  function toggleMediaType(value, active) {
    update({ selectedMediaTypes: active ? [...selected, value] : selected.filter(item => item !== value) });
  }

  return <SettingsCard title={labels.title} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.description}</Text>
    <View style={styles.grid}>
      <View style={styles.column}>
        <SelectField label={labels.frequency} name="frequency" value={model.frequency}
          options={options} palette={colors} onChange={event => update({ frequency: event.target.value })} />
      </View>
      <View style={styles.column}>
        <TextField label={labels.time} name="time" value={model.time} type="text"
          placeholder="03:00" disabled={!scheduled} palette={colors}
          onChangeText={value => update({ time: value })} />
      </View>
    </View>
    <View style={styles.sectionHeading}>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.content}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.contentHelp}</Text>
    </View>
    <View style={styles.toggleList}>
      {(model.mediaTypes || []).map(item => <ToggleChip key={item.value} label={item.label}
        value={selected.includes(item.value)} offLabel="Excluded" onLabel="Included"
        palette={colors} onChange={active => toggleMediaType(item.value, active)} />)}
      <ToggleChip label={labels.lists} value={Boolean(model.includeLists)} offLabel="Excluded"
        onLabel="Included" palette={colors} onChange={value => update({ includeLists: value })} />
      <ToggleChip label={labels.collection} value={Boolean(model.includeCollection)} offLabel="Excluded"
        onLabel="Included" palette={colors} onChange={value => update({ includeCollection: value })} />
    </View>
    {!hasContent ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{labels.noneSelected}</Text> : null}
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    <Button label={busy ? labels.submitBusy : scheduled ? labels.submitScheduled : labels.submitOnce}
      busy={busy} disabled={!hasContent || busy} onPress={onSubmit} palette={buttons} />
  </SettingsCard>;
}

export function ScheduledExportsCard({
  schedules = [],
  busyId,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onDelete,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = defaultLabels;
  const [pending, setPending] = useState(null);
  const [confirmError, setConfirmError] = useState('');
  const busy = Boolean(busyId);

  async function confirm() {
    setConfirmError('');
    try {
      await onDelete?.(pending);
      setPending(null);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not delete the schedule.');
    }
  }

  return <SettingsCard title={labels.scheduledTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.scheduledDescription}</Text>
    <StatusLine busy={false} error={error} success={success} palette={colors} />
    {schedules.length ? schedules.map(schedule => <View key={schedule.id}
      style={[styles.rowCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <View style={styles.rowBody}>
        <Text style={[styles.rowTitle, { color: colors.text }]}>CSV export · {schedule.schedule}</Text>
        <Text style={[styles.rowCopy, { color: colors.textMuted }]}>Media types: {schedule.mediaTypesLabel}</Text>
        <Text style={[styles.rowCopy, { color: colors.textMuted }]}>Lists: {schedule.includeLists ? 'Included' : 'Excluded'} · Collection: {schedule.includeCollection ? 'Included' : 'Excluded'}</Text>
        <Text style={[styles.rowCopy, { color: colors.textMuted }]}>Last dispatched: {schedule.lastRun || 'Never'}</Text>
        <Text style={[styles.rowCopy, { color: colors.textMuted }]}>Next backup: {schedule.nextRun || 'Not scheduled'}</Text>
      </View>
      <Button label={labels.deleteSchedule} tone="ghost-danger" busy={busyId === schedule.id}
        disabled={busy} onPress={() => { setConfirmError(''); setPending(schedule); }} palette={buttons} />
    </View>) : <View style={[styles.empty, { borderColor: colors.border }]}>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.scheduledEmpty}</Text>
    </View>}
    <ConfirmDialog visible={Boolean(pending)} title={labels.deleteScheduleTitle} message={labels.deleteScheduleCopy}
      warning={pending ? `${pending.schedule} stops running immediately.` : undefined}
      confirmLabel={labels.deleteSchedule} busy={Boolean(busyId)} error={confirmError}
      palette={colors} buttonPalette={buttons}
      onCancel={() => setPending(null)} onConfirm={confirm} />
  </SettingsCard>;
}

export function ExportHistoryCard({ results = [], palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const labels = defaultLabels;
  const [openId, setOpenId] = useState(null);
  return <SettingsCard title={labels.historyTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.historyDescription}</Text>
    {results.length ? results.map(result => {
      const tone = statusTones[result.status] || statusTones.PENDING;
      const expanded = openId === result.id;
      return <View key={result.id} style={[styles.rowCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
        <View style={styles.historyHeading}>
          <Text style={[styles.statusLabel, { color: tone.color }]}>{tone.label}</Text>
          <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{result.date}</Text>
        </View>
        {result.summary ? <Text style={[styles.rowCopy, { color: colors.textSecondary }]}>{result.summary}</Text> : null}
        {result.errors ? <>
          <Button label={expanded ? 'Hide details' : 'Show details'} tone="surface"
            onPress={() => setOpenId(expanded ? null : result.id)} palette={defaultButtonPalette} />
          {expanded ? <View style={[styles.errorBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            {String(result.errors).split('\n').map((line, index) => <Text key={index} style={[styles.errorLine, { color: colors.danger }]}>{line}</Text>)}
          </View> : null}
        </> : null}
      </View>;
    }) : <View style={[styles.empty, { borderColor: colors.border }]}>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.historyEmpty}</Text>
    </View>}
  </SettingsCard>;
}


export function RestoreBackupCard({
  fileName,
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onChoose,
  onRestore,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = defaultLabels;
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');

  async function restore() {
    setConfirmError('');
    try {
      await onRestore?.();
      setConfirming(false);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not restore the backup.');
    }
  }

  return <SettingsCard title={labels.restoreTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.restoreDescription}</Text>
    <Text style={[styles.warning, { color: colors.warning }]}>{labels.restoreWarning}</Text>
    <View style={[styles.fileRow, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.fileName, { color: fileName ? colors.textSecondary : colors.textMuted }]}>{fileName || 'No backup selected'}</Text>
      <Button label={labels.chooseBackup} tone="surface" onPress={onChoose} palette={buttons} />
    </View>
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    <Button label={busy ? labels.restoreBusy : labels.restore} tone="danger-solid" busy={busy}
      disabled={!fileName || busy} onPress={() => { setConfirmError(''); setConfirming(true); }} palette={buttons} />
    <ConfirmDialog visible={confirming} title={labels.restoreTitleConfirm} message={labels.restoreCopy}
      warning={fileName ? `Selected file: ${fileName}` : undefined} requirePhrase="RESTORE"
      phraseLabel="Type RESTORE to confirm." confirmLabel={labels.restore} busy={busy}
      error={confirmError} palette={colors} buttonPalette={buttons}
      onCancel={() => setConfirming(false)} onConfirm={restore} />
  </SettingsCard>;
}

export function RssFeedCard({
  model = {},
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onChange,
  onCopy,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const values = model.values || {};
  const mediaTypes = model.mediaTypes || [];
  const rows = model.rows || [];
  const preview = model.preview || {};
  const update = changes => onChange?.({ ...values, ...changes });

  return <SettingsCard title={labels.rssTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.rssDescription}</Text>
    <View style={styles.grid}>
      <View style={styles.column}>
        <SelectField label={labels.mediaType} name="mediaType" value={values.mediaType}
          options={mediaTypes} palette={colors} onChange={event => update({ mediaType: event.target.value })} />
      </View>
      <View style={styles.column}>
        <SelectField label={labels.row} name="rowKey" value={values.rowKey}
          options={rows} palette={colors} onChange={event => update({ rowKey: event.target.value })} />
      </View>
    </View>
    <View style={styles.toggleRow}>
      <View style={styles.column}>
        <ToggleChip label={labels.skipPlanning} value={Boolean(values.skipPlanning)} offLabel="Include"
          onLabel="Skipped" palette={colors} onChange={value => update({ skipPlanning: value })} />
      </View>
      <View style={styles.column}>
        <ToggleChip label={labels.skipCollected} value={Boolean(values.skipCollected)} offLabel="Include"
          onLabel="Skipped" palette={colors} onChange={value => update({ skipCollected: value })} />
      </View>
    </View>
    <View style={[styles.previewBox, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.preview}</Text>
      {preview.state === 'loading' ? <View style={styles.previewRow}>
        <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.previewLoading}</Text>
      </View> : preview.state === 'empty' ? <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.previewEmpty}</Text>
        : preview.items?.length ? <>
          {preview.title ? <Text style={[styles.rowCopy, { color: colors.textSecondary }]}>{preview.title}</Text> : null}
          {preview.items.map(item => <View key={item.id} style={styles.previewRow}>
            <Text style={[styles.rowTitle, { color: colors.textSecondary }]}>{item.title}</Text>
            <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{item.subtitle}</Text>
          </View>)}
        </> : <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.previewReady}</Text>}
    </View>
    <Text style={[styles.metaLabel, { color: colors.textMuted }]}>{labels.feedUrl}</Text>
    <View style={[styles.feedRow, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text selectable style={[styles.feedUrl, { color: colors.textSecondary }]}>{model.feedUrl || 'Choose a media type and row.'}</Text>
      <Button label={labels.copy} tone="surface" disabled={!model.feedUrl} onPress={onCopy} palette={buttons} />
    </View>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.feedHint}</Text>
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 12, lineHeight: 18 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  column: { flexGrow: 1, flexShrink: 1, flexBasis: 180, minWidth: 0 },
  toggleList: { gap: 10 },
  toggleRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  sectionHeading: { gap: 4 },
  sectionTitle: { fontSize: 14, fontWeight: '600' },
  status: { fontSize: 12, lineHeight: 18 },
  error: { fontSize: 12, lineHeight: 18 },
  rowCard: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  rowBody: { gap: 3 },
  rowTitle: { fontSize: 13, fontWeight: '600' },
  rowCopy: { fontSize: 12, lineHeight: 17 },
  empty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, padding: 14, alignItems: 'center' },
  historyHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  statusLabel: { fontSize: 12, fontWeight: '700' },
  errorBox: { borderWidth: 1, borderRadius: 6, padding: 8, gap: 2 },
  errorLine: { fontSize: 12, lineHeight: 17 },
  warning: { fontSize: 12, lineHeight: 18, fontWeight: '600' },
  fileRow: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' },
  fileName: { fontSize: 13, flexShrink: 1 },
  previewBox: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  previewRow: { gap: 2 },
  metaLabel: { fontSize: 12, fontWeight: '600' },
  feedRow: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' },
  feedUrl: { fontSize: 12, flexShrink: 1, flexGrow: 1, minWidth: 180 },
});
