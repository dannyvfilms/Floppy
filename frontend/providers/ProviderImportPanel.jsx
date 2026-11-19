import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { ConfirmDialog } from '../settings/ConfirmDialog';
import { SettingsCard } from '../settings/SettingsCard';

const USERNAME_LABELS = {
  mal: 'MyAnimeList Username',
  anilist: 'AniList Username',
  kitsu: 'Kitsu User ID',
  steam: 'Steam ID',
};

const DEFAULT_LABELS = {
  importTitle: 'Import options',
  syncTitle: 'Sync now',
  syncCopy: 'Import the latest data from your connected account.',
  syncAction: 'Sync now',
  syncing: 'Syncing…',
  frequency: 'Import Frequency',
  time: 'Import Time',
  mode: 'Import Mode',
  once: 'One Time Import',
  daily: 'Every Day',
  twoDays: 'Every 2 Days',
  modeNew: 'New Items Only',
  modeOverwrite: 'Overwrite Existing',
  start: 'Import',
  starting: 'Starting…',
  scheduleTitle: 'Import schedules',
  noSchedules: 'No recurring imports are scheduled.',
  nextRun: 'Next import',
  lastRun: 'Last run',
  deleteSchedule: 'Delete schedule',
  keep: 'Keep schedule',
  deleteTitle: 'Delete schedule',
  deleteMessage: 'Recurring imports from this schedule will stop.',
  unavailable: 'Imports for this provider are started from the web app.',
  activityTitle: 'Recent activity',
  noActivity: 'No import activity in the last seven days.',
  queued: 'Request sent.',
};

function formatWhen(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

/**
 * Import tab body: sync now, a username import (one time or recurring) and the
 * provider's schedules. Presentation only; the adapter owns every request and
 * returns a promise from each handler so failures show here with a retry path.
 */
export function ProviderImportPanel({
  slug,
  connection = {},
  schedules = [],
  defaults = {},
  labels,
  onSync,
  onImport,
  onDeleteSchedule,
  hasFileImport = false,
  palette = {},
  buttonPalette = {},
}) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const [form, setForm] = useState({
    username: '',
    mode: defaults.mode || 'new',
    frequency: 'once',
    time: defaults.time || '03:00',
  });
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const card = { ...palette, background: palette.surface ?? palette.background };

  async function run(kind, action) {
    if (pending) return;
    setPending(kind);
    setError('');
    setNotice('');
    try {
      const result = await action();
      setNotice(result?.messages?.[result.messages.length - 1] || copy.queued);
    } catch (reason) {
      setError(reason?.message || 'The request failed. Try again.');
    } finally {
      setPending('');
    }
  }

  const sections = [];
  if (connection.canSync) {
    sections.push(<SettingsCard key="sync" title={copy.syncTitle} palette={card}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.syncCopy}</Text>
      <View style={styles.row}>
        <Button label={pending === 'sync' ? copy.syncing : copy.syncAction} busy={pending === 'sync'}
          disabled={!!pending} onPress={() => run('sync', () => onSync?.())} palette={buttonPalette} />
      </View>
    </SettingsCard>);
  }
  if (connection.canSchedule) {
    const recurring = form.frequency !== 'once';
    sections.push(<SettingsCard key="import" title={copy.importTitle} palette={card}>
      <TextField id="import-username" name="user" label={USERNAME_LABELS[slug] || 'Username'}
        value={form.username} onChangeText={username => setForm(current => ({ ...current, username }))} palette={palette} />
      <SelectField id="import-mode" name="mode" label={copy.mode} value={form.mode} palette={palette}
        options={[{ value: 'new', label: copy.modeNew }, { value: 'overwrite', label: copy.modeOverwrite }]}
        onChange={event => setForm(current => ({ ...current, mode: event.target.value }))} />
      <SelectField id="import-frequency" name="frequency" label={copy.frequency} value={form.frequency} palette={palette}
        options={[{ value: 'once', label: copy.once }, { value: 'daily', label: copy.daily }, { value: '2days', label: copy.twoDays }]}
        onChange={event => setForm(current => ({ ...current, frequency: event.target.value }))} />
      {recurring ? <TextField id="import-time" name="time" label={copy.time} value={form.time} placeholder="HH:MM"
        onChangeText={time => setForm(current => ({ ...current, time }))} palette={palette} /> : null}
      <View style={styles.row}>
        <Button label={pending === 'import' ? copy.starting : copy.start} busy={pending === 'import'}
          disabled={!!pending || !form.username.trim()} onPress={() => run('import', () => onImport?.(form))}
          palette={buttonPalette} />
      </View>
    </SettingsCard>);
  }
  if (!sections.length) {
    if (!hasFileImport) sections.push(<Text key="none" style={[styles.copy, { color: palette.textMuted }]}>{copy.unavailable}</Text>);
  }

  return <View testID="provider-import-panel" style={styles.stack}>
    {sections}
    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: palette.success }]}>{notice}</Text> : null}
    {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text> : null}
    {connection.canSchedule || schedules.length ? <SettingsCard title={copy.scheduleTitle} palette={card}>
      {schedules.length ? schedules.map(row => <View key={row.task_name} style={styles.schedule}>
        <View style={styles.scheduleCopy}>
          <Text style={[styles.title, { color: palette.text }]} numberOfLines={2}>
            {[row.source, row.username].filter(Boolean).join(' · ') || row.task_name}
          </Text>
          <Text style={[styles.copy, { color: palette.textMuted }]}>
            {[row.frequency, row.next_run ? `${copy.nextRun}: ${formatWhen(row.next_run)}` : '',
              row.last_run ? `${copy.lastRun}: ${formatWhen(row.last_run)}` : ''].filter(Boolean).join(' · ')}
          </Text>
        </View>
        <Button label={copy.deleteSchedule} tone="danger-solid" disabled={!!pending}
          onPress={() => setDeleteTarget(row)} palette={buttonPalette} />
      </View>) : <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.noSchedules}</Text>}
    </SettingsCard> : null}
    <ConfirmDialog visible={!!deleteTarget} title={copy.deleteTitle} message={copy.deleteMessage}
      confirmLabel={copy.deleteSchedule} cancelLabel={copy.keep} busy={pending === 'delete'}
      palette={palette} buttonPalette={buttonPalette}
      onCancel={() => setDeleteTarget(null)}
      onConfirm={() => {
        const target = deleteTarget;
        setDeleteTarget(null);
        run('delete', () => onDeleteSchedule?.(target.task_name));
      }} />
  </View>;
}

/** Activity tab body: the provider's recent import runs and schedules. */
export function ProviderActivityList({ activity = [], schedules = [], labels, palette = {} }) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const card = { ...palette, background: palette.surface ?? palette.background };
  return <View testID="provider-activity-list" style={styles.stack}>
    <SettingsCard title={copy.activityTitle} palette={card}>
      {activity.length ? activity.map((row, index) => <View key={`${row.date}-${index}`} style={styles.activity}>
        <Text style={[styles.title, { color: palette.text }]}>{row.status}</Text>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{formatWhen(row.date)}</Text>
        {row.summary ? <Text style={[styles.copy, { color: palette.textSecondary }]}>{row.summary}</Text> : null}
      </View>) : <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.noActivity}</Text>}
    </SettingsCard>
    {schedules.length ? <SettingsCard title={copy.scheduleTitle} palette={card}>
      {schedules.map(row => <Text key={row.task_name} style={[styles.copy, { color: palette.textSecondary }]}>
        {[row.username, row.frequency, row.next_run ? formatWhen(row.next_run) : ''].filter(Boolean).join(' · ')}
      </Text>)}
    </SettingsCard> : null}
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  copy: { fontSize: 13, lineHeight: 19 },
  title: { fontSize: 14, fontWeight: '600', lineHeight: 20 },
  schedule: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  scheduleCopy: { flexShrink: 1, flexGrow: 1, minWidth: 160, gap: 2 },
  activity: { gap: 2, paddingVertical: 4 },
});
