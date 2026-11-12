import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';
import { BackupStatus } from './BackupStatus';
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
  title: 'Export Data',
  description: 'Export your media, ratings, and lists as CSV, or create a recurring export schedule and download the initial CSV immediately. This is a data export, not a database backup. It does not restore your account, integrations, or preferences, and it cannot replace a damaged database file.',
  frequency: 'Export Frequency',
  time: 'Export Time',
  content: 'Export Content',
  contentHelp: 'Keep at least one media type, Custom Lists, or Collection enabled. Keep every media type and both additional content options enabled for a full export; turn off all media types and leave Lists or Collection enabled for a subset export.',
  lists: 'Custom Lists',
  collection: 'Collection',
  submitOnce: 'Export as CSV',
  submitScheduled: 'Export as CSV and Save Schedule',
  submitBusy: 'Preparing export…',
  noneSelected: 'Choose at least one media type, Custom Lists, or Collection.',
  scheduledTitle: 'Active Scheduled Exports',
  scheduledDescription: 'Automated exports that run on a schedule. These will continue until disabled.',
  scheduledEmpty: 'No scheduled exports configured',
  scheduledEmptyHint: 'Set up a schedule above to automatically export your data',
  deleteSchedule: 'Delete schedule',
  deleteScheduleTitle: 'Delete export schedule?',
  deleteScheduleCopy: 'This stops the recurring CSV export. Files already written stay on the server.',
  historyTitle: 'Export History',
  historyDescription: 'Showing export activity from the last 7 days.',
  historyEmpty: 'No exports in the last 7 days',
  historyEmptyHint: 'Set up a schedule to see the history here',
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
  icon,
  model = {},
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  backup = [],
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

  return <SettingsCard title={labels.title} icon={icon} palette={colors}>
    <View style={{ gap: colors.pageCards ? 0 : 12 }}>
      <Text style={[styles.copy, { color: colors.textMuted }, colors.pageCards && [styles.pageCopy, { marginBottom: 8 }]]}>{labels.description}</Text>
      <BackupStatus sections={backup} palette={colors} />
    </View>
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

export function ExportOtherSitesCard({ icon, busy = false, error, success, palette = {}, buttonPalette = {}, onLetterboxd }) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  return <SettingsCard title="Export for Other Websites" icon={icon} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>Unlike the export above, these exports are trimmed and reshaped to match what a specific external site expects.</Text>
    <View style={[styles.rowCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>Letterboxd</Text>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>Watched movies with ratings and diary dates, ready for Letterboxd's CSV import.</Text>
      <Button label={busy ? 'Preparing export\u2026' : 'Export for Letterboxd'} tone="surface" busy={busy} disabled={busy}
        onPress={onLetterboxd} palette={buttons} />
    </View>
    <StatusLine busy={false} error={error} success={success} palette={colors} />
  </SettingsCard>;
}

export function ImportSettingsCard({
  values = {}, frequencies = [], modes = [], busy = false, error, success, palette = {}, onChange,
}) {
  const colors = { ...defaultPalette, ...palette };
  const update = changes => onChange?.({ ...values, ...changes });
  return <SettingsCard title="Import Settings" palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>These preferences are shared across imports that support them.</Text>
    <View style={styles.grid}>
      <View style={styles.column}>
        <SelectField label="Import Frequency" name="frequency" value={values.frequency}
          options={frequencies} palette={colors} onChange={event => update({ frequency: event.target.value })} />
      </View>
      <View style={styles.column}>
        <SelectField label="Import Mode" name="mode" value={values.mode}
          options={modes} palette={colors} onChange={event => update({ mode: event.target.value })} />
      </View>
    </View>
    {values.frequency && values.frequency !== 'once' ? <TextField label="Import Time" name="time"
      value={values.time} type="text" placeholder="03:00" palette={colors}
      onChangeText={value => update({ time: value })} /> : null}
    <StatusLine busy={busy ? 'Saving\u2026' : false} error={error} success={success} palette={colors} />
  </SettingsCard>;
}

export function ScheduledExportsCard({
  icon,
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

  return <SettingsCard title={labels.scheduledTitle} icon={icon} palette={colors}>
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
      <Text style={[styles.rowCopy, { color: colors.textSecondary }]}>{labels.scheduledEmpty}</Text>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.scheduledEmptyHint}</Text>
    </View>}
    <ConfirmDialog visible={Boolean(pending)} title={labels.deleteScheduleTitle} message={labels.deleteScheduleCopy}
      warning={pending ? `${pending.schedule} stops running immediately.` : undefined}
      confirmLabel={labels.deleteSchedule} busy={Boolean(busyId)} error={confirmError}
      palette={colors} buttonPalette={buttons}
      onCancel={() => setPending(null)} onConfirm={confirm} />
  </SettingsCard>;
}

export function ExportHistoryCard({ icon, results = [], palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const labels = defaultLabels;
  const [openId, setOpenId] = useState(null);
  return <SettingsCard title={labels.historyTitle} icon={icon} palette={colors}>
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
      <Text style={[styles.rowCopy, { color: colors.textSecondary }]}>{labels.historyEmpty}</Text>
      <Text style={[styles.rowCopy, { color: colors.textMuted }]}>{labels.historyEmptyHint}</Text>
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

  if (model.sessionRequired) return <SettingsCard title={labels.rssTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>Sign in with your username and password to manage this.</Text>
  </SettingsCard>;

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

const maintenanceLabels = {
  title: 'Library maintenance',
  templateCopy: 'Download a CSV template for importing your own data.',
  template: 'Download an import template',
  repairCopy: 'Fold duplicated Anime and TV tracking rows back together, or move tracked TV shows to your default TV provider. These run in the background.',
  repair: 'Repair duplicate anime libraries',
  convert: 'Move TV shows to default provider',
  dangerTitle: 'Danger Zone',
  dangerCopy: 'Permanently delete every tracked entry for one media type in your account, including its progress, ratings, notes, and history. This cannot be undone.',
  mediaTypeToDelete: 'Media type to delete',
  choose: 'Choose a media type...',
  deleteMetadata: 'Also remove metadata no one else uses',
  deleteType: 'Delete Selected Type',
  confirmTitle: 'Are you sure?',
};

// Import template, library repair and the media-type danger zone from the web
// Data page. The adapter supplies the deletable media types and the actions;
// every action resolves with a message or rejects with an Error.
export function LibraryMaintenanceCard({
  mediaTypes = [],
  duplicateAnimeCount,
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  labels = {},
  onDownloadTemplate,
  onRepairAnime,
  onConvertTv,
  onDelete,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...maintenanceLabels, ...labels };
  const [mediaType, setMediaType] = useState('');
  const [deleteMetadata, setDeleteMetadata] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  const options = [{ value: '', label: copy.choose }, ...mediaTypes];

  async function confirmDelete() {
    setConfirmError('');
    try {
      await onDelete?.({ mediaType, deleteMetadata });
      setConfirming(false);
      setMediaType('');
      setDeleteMetadata(false);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not delete the library.');
    }
  }

  const label = mediaTypes.find(option => option.value === mediaType)?.label || mediaType;
  return <SettingsCard title={colors.pageCards ? undefined : copy.title} framed={!colors.pageCards} palette={colors}>
    {!colors.pageCards ? <>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.templateCopy}</Text>
      <Button label={copy.template} tone="surface" disabled={busy} onPress={onDownloadTemplate} palette={buttons} />
    </> : null}
    {duplicateAnimeCount == null || duplicateAnimeCount > 0 ? <>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.repairCopy}</Text>
      <View style={styles.toggleRow}>
        <Button label={copy.repair} tone="surface" disabled={busy} onPress={onRepairAnime} palette={buttons} />
        {onConvertTv ? <Button label={copy.convert} tone="surface" disabled={busy} onPress={onConvertTv} palette={buttons} /> : null}
      </View>
    </> : null}
    <View style={[styles.previewBox, { backgroundColor: colors.surfaceStrong, borderColor: colors.danger }, colors.pageCards && { padding: 20, borderWidth: 0, gap: 16 }]}>
      <Text style={[styles.sectionTitle, { color: colors.danger }, colors.pageCards && { fontSize: 16, lineHeight: 24, fontWeight: '500' }]}>{copy.dangerTitle}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }, colors.pageCards && styles.pageCopy]}>{copy.dangerCopy}</Text>
      <SelectField label={copy.mediaTypeToDelete} name="mediaType" value={mediaType} options={options}
        palette={colors} onChange={event => setMediaType(event.target.value)} />
      {!colors.pageCards ? <ToggleChip label={copy.deleteMetadata} value={deleteMetadata} offLabel="Keep" onLabel="Remove"
        palette={colors} onChange={setDeleteMetadata} /> : null}
      <Button label={copy.deleteType} tone="danger-solid" disabled={!mediaType || busy}
        onPress={() => { setConfirmError(''); setConfirming(true); }} palette={buttons} />
    </View>
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    <ConfirmDialog visible={confirming} title={copy.confirmTitle}
      message={`This permanently deletes every ${label} entry in your account.`}
      warning="This cannot be undone." requirePhrase="DELETE" phraseLabel="Type DELETE to confirm."
      confirmLabel={copy.deleteType} busy={busy} error={confirmError} palette={colors}
      buttonPalette={buttons} onCancel={() => setConfirming(false)} onConfirm={confirmDelete}>
      {colors.pageCards ? <ToggleChip label={copy.deleteMetadata} value={deleteMetadata} offLabel="Keep" onLabel="Remove"
        palette={colors} onChange={setDeleteMetadata} /> : null}
    </ConfirmDialog>
  </SettingsCard>;
}

const styles = StyleSheet.create({
  pageCopy: { fontSize: 14, lineHeight: 20 },
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
