import React, { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { SettingsCard } from '../settings/SettingsCard';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';

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
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const defaultLabels = {
  preferences: 'Import preferences',
  editable: 'Editable',
  readOnly: 'Read-only',
  mode: 'Import Mode',
  override: 'Override mode',
  modeHelp: 'New items leaves existing entries unchanged. Overwrite replaces matching imported entries.',
  frequency: 'Import Frequency',
  time: 'Import Time',
  watchlistStatus: 'Watchlist status',
  watchlistTag: 'Watchlist tag',
  saving: 'Saving…',
  saved: 'Preferences saved',
  saveError: 'Could not save preferences. Try again.',
  retry: 'Retry',
  options: 'Import options',
  description: 'Import your library using the selected preferences.',
  publicLabel: 'Public',
  privateLabel: 'Private',
  username: 'Public username',
  usernamePlaceholder: 'Public username',
  import: 'Import',
  importing: 'Importing…',
  imported: 'Import started',
  importError: 'Could not start the import. Try again.',
  privateRequires: 'Private imports require provider credentials.',
  configure: 'Configure Connection',
  modeUnsupported: 'This import mode is not supported by this provider.',
  oneTime: 'One Time Import',
};

const modeOptions = [
  { value: 'history', label: 'History' },
  { value: 'watchlist', label: 'Watchlist' },
  { value: 'update_collection', label: 'Collection' },
];

const frequencyOptions = [
  { value: 'once', label: 'One Time Import' },
  { value: 'daily', label: 'Every Day' },
  { value: '2days', label: 'Every 2 Days' },
];

const overrideOptions = [
  { value: 'new', label: 'New Items Only' },
  { value: 'overwrite', label: 'Overwrite Existing' },
];

function statusPalette(colors, tone) {
  if (tone === 'success') return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  if (tone === 'warning') return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  if (tone === 'info') return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  return colors;
}

function Select({ id, label, value, options, disabled, colors, onChange }) {
  return <SelectField id={id} name={id} label={label} value={value} options={options}
    disabled={disabled} palette={colors} onChange={event => onChange(event.target.value)} />;
}

/**
 * Shared import-preference card with the browser auto-save contract expressed as
 * an async intent. The caller owns persistence and the server's authoritative
 * validation; this component only renders selected/disabled/saving/error states.
 */
export function ImportPreferencesCard({
  model,
  onValuesChange,
  onSave,
  palette = {},
  buttonPalette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const [values, setValues] = useState(() => ({ ...model.values }));
  const [saveState, setSaveState] = useState('');
  const version = useRef(0);

  function update(next) {
    setValues(next);
    onValuesChange?.(next);
  }

  function save(next) {
    update(next);
    if (!onSave) return;
    const revision = ++version.current;
    setSaveState('saving');
    Promise.resolve(onSave(next))
      .then(() => { if (revision === version.current) setSaveState('saved'); })
      .catch(() => { if (revision === version.current) setSaveState('error'); });
  }

  const editable = model.editable !== false;
  const history = ['history', 'overwrite'].includes(values.mode);
  const fixed = model.fixed;
  const tone = fixed || !editable ? 'warning' : 'info';
  const badge = fixed || !editable ? labels.readOnly : labels.editable;

  return <SettingsCard title={model.title || labels.preferences} badge={badge}
    palette={statusPalette(colors, tone)}>
    {fixed ? <View style={styles.fields}>
      <View><Text style={[styles.caption, { color: colors.textMuted }]}>{labels.mode}</Text>
        <Text style={[styles.value, { color: colors.text }]}>{fixed.mode}</Text></View>
      <View><Text style={[styles.caption, { color: colors.textMuted }]}>{labels.frequency}</Text>
        <Text style={[styles.value, { color: colors.text }]}>{fixed.frequency}</Text></View>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{fixed.explanation}</Text>
    </View> : <View style={styles.fields}>
      <Select id="import-mode" label={labels.mode} value={history ? 'history' : values.mode}
        options={model.modeOptions || modeOptions} disabled={!editable} colors={colors}
        onChange={mode => save({ ...values, mode: mode === 'history' ? 'new' : mode })} />
      {history ? <>
        <Select id="import-override" label={labels.override} value={values.mode}
          options={model.overrideOptions || overrideOptions} disabled={!editable} colors={colors}
          onChange={mode => save({ ...values, mode })} />
        <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.modeHelp}</Text>
      </> : null}
      {values.mode === 'watchlist' ? <>
        <Select id="watchlist-status" label={labels.watchlistStatus} value={values.watchlistStatus}
          options={model.statuses || []} disabled={!editable} colors={colors}
          onChange={watchlistStatus => save({ ...values, watchlistStatus })} />
        <Select id="watchlist-tag" label={labels.watchlistTag} value={values.watchlistTag}
          options={model.tags || []} disabled={!editable} colors={colors}
          onChange={watchlistTag => save({ ...values, watchlistTag })} />
      </> : null}
      {model.fixedFrequency ? <View>
        <Text style={[styles.caption, { color: colors.textMuted }]}>{labels.frequency}</Text>
        <Select id="import-frequency" label={labels.frequency} value="once"
          options={[{ value: 'once', label: labels.oneTime }]} disabled colors={colors} onChange={() => {}} />
        <Text style={[styles.copy, { color: colors.textMuted }]}>{model.fixedFrequencyHelp}</Text>
      </View> : <>
        <Select id="import-frequency" label={labels.frequency} value={values.frequency}
          options={model.frequencyOptions || frequencyOptions} disabled={!editable} colors={colors}
          onChange={frequency => save({ ...values, frequency })} />
        {values.frequency !== 'once' ? <TextField id="import-time" name="import-time" type="time"
          label={labels.time} value={values.time} disabled={!editable} required palette={colors}
          onChangeText={time => save({ ...values, time })} /> : null}
      </>}
    </View>}
    <Text accessibilityRole="status" style={[styles.copy, { color: saveState === 'error' ? colors.danger : colors.textMuted }]}>
      {saveState === 'saving' ? labels.saving : saveState === 'saved' ? labels.saved : saveState === 'error' ? labels.saveError : ''}
    </Text>
    {saveState === 'error' ? <Button label={labels.retry} tone="surface" onPress={() => save(values)} palette={buttons} /> : null}
  </SettingsCard>;
}

/**
 * Shared provider Import tab: preferences plus the public/private provider form.
 * The adapter supplies authentication rules and the action; credentials are never
 * props here.
 */
export function ImportSettings({
  model,
  onImport,
  onSavePreferences,
  onConfigure,
  palette = {},
  buttonPalette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const [preferences, setPreferences] = useState(() => ({ ...(model.preferences?.values || {}) }));
  const [privateImport, setPrivateImport] = useState(Boolean(model.privateImport));
  const [username, setUsername] = useState(model.username || '');
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const blocked = !['new', 'overwrite'].includes(preferences.mode);
  const privateBlocked = privateImport && !model.configured;

  async function submit() {
    if (pending || blocked || privateBlocked) return;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await onImport?.({ private: privateImport, username, preferences });
      setNotice(labels.imported);
    } catch (reason) {
      setError(reason?.message || labels.importError);
    } finally {
      setPending(false);
    }
  }

  return <View style={styles.stack}>
    <ImportPreferencesCard
      model={{ ...model.preferences, values: preferences }}
      onValuesChange={next => setPreferences(next)}
      onSave={onSavePreferences}
      palette={palette}
      buttonPalette={buttonPalette}
    />
    <SettingsCard title={model.title || labels.options} palette={colors} headerAction={
      <ToggleChip value={privateImport} onChange={next => { setPrivateImport(next); setNotice(''); setError(''); }}
        offLabel={labels.publicLabel} onLabel={labels.privateLabel} palette={colors} />
    }>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{model.description || labels.description}</Text>
      {privateBlocked ? <View style={[styles.notice, { borderColor: colors.warning }]}>
        <Text style={[styles.copy, { color: colors.textSecondary }]}>{labels.privateRequires}</Text>
        <Button label={labels.configure} tone="surface" onPress={onConfigure} palette={buttons} />
      </View> : <>
        {!privateImport ? <TextField id="import-username" name="user" label={labels.username}
          value={username} required placeholder={labels.usernamePlaceholder} palette={colors}
          onChangeText={next => { setUsername(next); setNotice(''); setError(''); }} /> : null}
        <View style={styles.actions}>
          <Button label={pending ? labels.importing : labels.import} busy={pending}
            disabled={pending || blocked} onPress={submit} palette={buttons} />
        </View>
      </>}
      {blocked ? <Text style={[styles.copy, { color: colors.textMuted }]}>{model.modeUnsupported || labels.modeUnsupported}</Text> : null}
      {notice ? <Text accessibilityRole="status" style={[styles.copy, { color: colors.success }]}>{notice}</Text> : null}
      {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>{error}</Text> : null}
    </SettingsCard>
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  fields: { gap: 12 },
  caption: { fontSize: 12 },
  value: { fontSize: 14 },
  copy: { fontSize: 12, lineHeight: 17 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 10 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
