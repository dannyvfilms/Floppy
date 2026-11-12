import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';

export const connectionsCopy = {
  title: 'Connections',
  copy: 'Linked services, watched-state sync and applications waiting for approval.',
  accountsTitle: 'Connected services',
  noAccounts: 'No services are connected yet. Open Providers to connect one.',
  syncTitle: 'Watched-state sync',
  syncCopy: 'Keep completion state in step with your media servers. History imports are configured separately, per connection.',
  noSync: 'No connections yet. Connect a media server above and it will appear here.',
  direction: 'Direction',
  pause: 'Pause',
  resume: 'Resume',
  paused: 'Paused',
  lastChecked: 'Last checked',
  notChecked: 'Not checked yet',
  active: 'Active',
  save: 'Save',
  saved: 'Saved.',
  pending: 'Pending',
  failed: 'Failed',
  unavailable: 'Unavailable until its adapter is verified',
  conflictsTitle: 'Needs your decision',
  conflictsCopy: 'Both sides changed while they were out of contact. Sync is paused for these items only. Everything else keeps flowing.',
  watched: 'Watched',
  unwatched: 'Unwatched',
  deviceTitle: 'Approve a device',
  deviceCopy: 'Enter the code shown on the device or application you want to allow.',
  deviceCode: 'Device code',
  deviceLookup: 'Look up code',
  approve: 'Approve',
  deny: 'Deny',
  deviceAllowed: 'Application authorised.',
  deviceDenied: 'Application denied.',
  loading: 'Loading connections…',
  retry: 'Retry',
};

function Notice({ error, children, palette }) {
  if (!children) return null;
  return <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite"
    style={[styles.copy, { color: error ? palette.danger : palette.success }]}>{children}</Text>;
}

function DeviceApproval({ device, copy, palette, buttonPalette }) {
  const [code, setCode] = useState('');
  const [found, setFound] = useState(null);
  const [state, setState] = useState({ busy: '', error: '', done: '' });

  async function run(kind, action) {
    if (state.busy) return;
    setState({ busy: kind, error: '', done: '' });
    try {
      const result = await action();
      setState({ busy: '', error: '', done: result?.done || '' });
    } catch (reason) {
      setState({ busy: '', error: reason?.message || 'The request failed. Try again.', done: '' });
    }
  }

  if (device.sessionRequired) return <SettingsCard title={copy.deviceTitle} palette={{ ...palette, background: palette.surface ?? palette.background }}>
    <Text style={[styles.copy, { color: palette.textMuted }]}>Sign in with your username and password to manage this.</Text>
  </SettingsCard>;

  return <SettingsCard title={copy.deviceTitle} palette={{ ...palette, background: palette.surface ?? palette.background }}>
    <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.deviceCopy}</Text>
    <TextField id="device-code" name="user_code" label={copy.deviceCode} value={code} placeholder="ABCD-1234"
      onChangeText={value => { setCode(value); setFound(null); }} palette={palette} />
    <View style={styles.row}>
      <Button label={copy.deviceLookup} tone="surface" busy={state.busy === 'lookup'} disabled={!code.trim() || !!state.busy}
        onPress={() => run('lookup', async () => { setFound(await device.lookup(code)); return {}; })} palette={buttonPalette} />
    </View>
    {found ? <View style={styles.stack}>
      <Text style={[styles.title, { color: palette.text }]}>{found.application}</Text>
      {found.scopes.map(scope => <Text key={scope.scope} style={[styles.copy, { color: palette.textSecondary }]}>
        {scope.label}{scope.description ? `: ${scope.description}` : ''}
      </Text>)}
      <View style={styles.row}>
        <Button label={copy.approve} busy={state.busy === 'approve'} disabled={!!state.busy} palette={buttonPalette}
          onPress={() => run('approve', async () => { await device.decide(code, 'approve'); setFound(null); setCode(''); return { done: copy.deviceAllowed }; })} />
        <Button label={copy.deny} tone="danger-solid" busy={state.busy === 'deny'} disabled={!!state.busy} palette={buttonPalette}
          onPress={() => run('deny', async () => { await device.decide(code, 'deny'); setFound(null); setCode(''); return { done: copy.deviceDenied }; })} />
      </View>
    </View> : null}
    <Notice error palette={palette}>{state.error}</Notice>
    <Notice palette={palette}>{state.done}</Notice>
  </SettingsCard>;
}

function SyncRow({ row, copy, palette, buttonPalette, onDirection, onPause }) {
  const [error, setError] = useState('');
  const [direction, setDirection] = useState(row.direction);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => setDirection(row.direction), [row.direction]);
  async function guard(action) {
    if (busy) return;
    setError('');
    setSaved(false);
    setBusy(true);
    try { await action(); setSaved(true); } catch (reason) { setError(reason?.message || 'The request failed. Try again.'); }
    finally { setBusy(false); }
  }
  const card = { ...palette, background: palette.surface ?? palette.background };
  return <SettingsCard title={row.label} badge={row.kill_switch ? copy.paused : row.is_operational ? copy.active : row.status} palette={card}>
    <Text style={[styles.copy, { color: palette.textMuted }]}>
      {row.last_reconciled_label ? `${copy.lastChecked} ${row.last_reconciled_label}` : copy.notChecked}
      {row.pending_deliveries ? ` · ${row.pending_deliveries} pending` : ''}
      {row.failed_deliveries ? ` · ${row.failed_deliveries} failed` : ''}
      {row.open_conflicts ? ` · ${row.open_conflicts} to decide` : ''}
    </Text>
    {row.last_error_message ? <Text style={[styles.copy, { color: palette.danger }]}>{row.last_error_message}</Text> : null}
    <SelectField id={`direction-${row.id}`} name="direction" label={copy.direction} palette={palette}
      options={row.direction_choices} value={direction} disabled={busy}
      onChange={event => { setDirection(event.target.value); setSaved(false); }} />
    <View style={styles.row}>
      <Button label={copy.save} disabled={busy} busy={busy} onPress={() => guard(() => onDirection(row, direction))} palette={buttonPalette} />
      <Button label={row.kill_switch ? copy.resume : copy.pause} tone="surface" onPress={() => guard(() => onPause(row, !row.kill_switch))}
        disabled={busy} palette={buttonPalette} />
    </View>
    <View style={styles.stack}>
      {row.capabilities.map(capability => <Text key={capability.code} style={[styles.copy, {
        color: capability.unavailable ? palette.warning : capability.approved ? palette.success : palette.textMuted,
      }]}>
        {capability.unavailable ? 'Unavailable' : capability.approved ? 'On' : capability.supported ? 'Off' : 'Not supported'}
        {` · ${capability.label}${capability.unavailable ? ' (not verified for this provider yet)' : ''}`}
      </Text>)}
    </View>
    <Notice error palette={palette}>{error}</Notice>
    <Notice palette={palette}>{saved ? copy.saved : ''}</Notice>
  </SettingsCard>;
}

/**
 * Connections page: linked services with health, watched-state sync per
 * connection (direction and kill switch), open conflicts, and device approval.
 */
export function ConnectionsView({
  data,
  state = 'ready',
  error = '',
  labels,
  palette = {},
  buttonPalette = {},
  onRetry,
  onOpenProvider,
  onDirection,
  onPause,
  onResolve,
  device,
  heading = true,
}) {
  const copy = { ...connectionsCopy, ...(labels || {}) };
  const [conflictError, setConflictError] = useState('');
  const card = { ...palette, background: palette.surface ?? palette.background };
  const head = <View style={styles.stack}>
    {heading ? <Text role="heading" aria-level={2} style={[styles.heading, { color: palette.text }]}>{copy.title}</Text> : null}
    <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.copy}</Text>
  </View>;
  if (state === 'loading') {
    return <View style={styles.page}>{head}<Text style={[styles.copy, { color: palette.textMuted }]}>{copy.loading}</Text></View>;
  }
  if (state === 'error') {
    return <View style={styles.page}>{head}
      <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text>
      {onRetry ? <View style={styles.row}><Button label={copy.retry} tone="surface" onPress={onRetry} palette={buttonPalette} /></View> : null}
    </View>;
  }
  const { accounts = [], sync = [], conflicts = [] } = data || {};
  return <View style={styles.page} testID="connections-view">
    {head}
    {conflicts.length ? <SettingsCard title={`${conflicts.length} ${conflicts.length === 1 ? 'item needs' : 'items need'} your decision`} palette={card}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.conflictsCopy}</Text>
      {conflicts.map(conflict => <View key={conflict.id} style={styles.stack}>
        <Text style={[styles.title, { color: palette.text }]} numberOfLines={2}>{conflict.title}</Text>
        <Text style={[styles.copy, { color: palette.textSecondary }]}>
          {conflict.client_label || conflict.client_kind} says {conflict.remote?.watched ? 'watched' : 'unwatched'}; Floppy says {conflict.local?.watched ? 'watched' : 'unwatched'}.
        </Text>
        <View style={styles.row}>
          {[true, false].map(watched => <Button key={String(watched)} tone="surface" label={watched ? copy.watched : copy.unwatched}
            palette={buttonPalette}
            onPress={async () => {
              setConflictError('');
              try { await onResolve(conflict, watched); } catch (reason) { setConflictError(reason?.message || 'The request failed. Try again.'); }
            }} />)}
        </View>
      </View>)}
      <Notice error palette={palette}>{conflictError}</Notice>
    </SettingsCard> : null}
    <View style={styles.stack}>
      <Text role="heading" aria-level={3} style={[styles.section, { color: palette.text }]}>{copy.accountsTitle}</Text>
      {accounts.length ? accounts.map(account => <Pressable key={account.slug} accessibilityRole="button"
        accessibilityLabel={account.label} onPress={() => onOpenProvider?.(account.slug)}
        style={({ pressed }) => [styles.account, { borderColor: palette.border, backgroundColor: pressed ? palette.surfaceStrong : palette.surface }]}>
        <Text style={[styles.title, { color: palette.text }]}>{account.label}</Text>
        <Chip label={account.status.label} palette={palette} />
      </Pressable>) : <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.noAccounts}</Text>}
    </View>
    <View style={styles.stack}>
      <Text role="heading" aria-level={3} style={[styles.section, { color: palette.text }]}>{copy.syncTitle}</Text>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.syncCopy}</Text>
      {sync.length ? sync.map(row => <SyncRow key={row.id} row={row} copy={copy} palette={palette}
        buttonPalette={buttonPalette} onDirection={onDirection} onPause={onPause} />)
        : <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.noSync}</Text>}
    </View>
    {device ? <DeviceApproval device={device} copy={copy} palette={palette} buttonPalette={buttonPalette} /> : null}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 20, minWidth: 0 },
  stack: { gap: 8 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  heading: { fontSize: 22, fontWeight: '600', lineHeight: 28 },
  section: { fontSize: 18, fontWeight: '600', lineHeight: 26 },
  title: { fontSize: 14, fontWeight: '600', lineHeight: 20, flexShrink: 1 },
  copy: { fontSize: 13, lineHeight: 19 },
  account: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10, borderWidth: 1, borderRadius: 10, padding: 12 },
});
