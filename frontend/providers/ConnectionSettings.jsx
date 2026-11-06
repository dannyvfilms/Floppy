import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { SettingsCard } from '../settings/SettingsCard';
import { TextField } from '../ui/TextField';

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
  save: 'Save',
  saving: 'Saving…',
  saved: 'Credentials saved',
  saveError: 'Could not save credentials. Try again.',
  remove: 'Remove stored credentials',
  personalSave: 'Save personal key',
  personalSaving: 'Saving…',
  personalSaved: 'Personal key saved',
  personalError: 'Could not save the personal key. Try again.',
  instanceHelp: 'These credentials are shared across the instance.',
  personalHelp: 'Your key may avoid shared instance or bundled rate limits.',
  fallback: 'Leave a field blank to keep the current fallback.',
  getKey: 'Get a key from {name}',
  readOnly: 'Read-only',
  editable: 'Editable',
  publicApi: 'Public API',
  readOnlyHelp: 'Read-only: explain instance credential access',
  close: 'Close',
  stored: 'Stored',
  notSet: 'Not set',
  your: 'Your',
  environment: 'Environment',
  bundled: 'Bundled default',
};

function statusPalette(colors, tone) {
  if (tone === 'success') return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  if (tone === 'warning') return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  if (tone === 'info') return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  return colors;
}

function fieldHelp(field, labels) {
  if (field.help) return field.help;
  if (field.environment) return `${labels.environment}: ${field.setting}`;
  if (field.usingDefault) return labels.bundled;
  if (field.disabled) return labels.stored;
  return undefined;
}

function FieldControl({ field, value, disabled, onChange, colors, labels }) {
  if (field.type === 'select') {
    return <SelectField
      id={field.name}
      name={field.name}
      label={field.label}
      value={value ?? field.value ?? field.options?.[0]?.value}
      options={field.options || []}
      disabled={disabled}
      help={field.help}
      palette={colors}
      onChange={event => onChange(event.target.value)}
    />;
  }
  const masked = field.stored && !value ? field.maskedPreview || '••••••••' : undefined;
  return <TextField
    id={field.name}
    name={field.name}
    label={field.label}
    type={field.secret ? 'password' : field.type || 'text'}
    value={value}
    disabled={disabled}
    required={field.required}
    placeholder={field.placeholder || (field.disabled ? fieldHelp(field, labels) : undefined)}
    help={fieldHelp(field, labels)}
    maskedPreview={masked}
    autoComplete="off"
    palette={colors}
    onChangeText={text => onChange(text)}
  />;
}

/**
 * Shared provider credential card. The adapter supplies field metadata and
 * actions; entered secrets stay in local form state and are never serialized by
 * this presentation.
 */
export function ConnectionSettings({
  model,
  onSave,
  onClear,
  onOpenLink,
  showKeyLink = true,
  palette = {},
  buttonPalette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const [instanceValues, setInstanceValues] = useState(() => Object.fromEntries(
    (model.fields || []).filter(field => field.value !== undefined && field.value !== null)
      .map(field => [field.name, field.value]),
  ));
  const [personalValues, setPersonalValues] = useState(() => Object.fromEntries(
    (model.personalFields || []).filter(field => field.value !== undefined && field.value !== null)
      .map(field => [field.name, field.value]),
  ));
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const editable = model.editable !== false;
  const badge = statusPalette(colors, model.statusTone || (model.publicAccess ? 'success' : editable ? 'info' : 'warning'));
  const tone = model.statusTone || (model.publicAccess ? 'success' : editable ? 'info' : 'warning');
  const status = model.statusLabel || (model.publicAccess ? labels.publicApi : editable ? labels.editable : labels.readOnly);

  function setField(setter, name, value) {
    setter(current => ({ ...current, [name]: value }));
    setNotice(null);
    setError(null);
  }

  async function submit(kind) {
    if (pending) return;
    setPending(kind);
    setError(null);
    setNotice(null);
    try {
      await onSave?.(kind, kind === 'personal' ? personalValues : instanceValues);
      setNotice({ kind, text: kind === 'personal' ? labels.personalSaved : labels.saved });
    } catch (reason) {
      setError({ kind, text: reason?.message || (kind === 'personal' ? labels.personalError : labels.saveError) });
    } finally {
      setPending('');
    }
  }

  async function clear() {
    if (pending) return;
    setPending('clear');
    setError(null);
    setNotice(null);
    try {
      await onClear?.();
      setInstanceValues({});
      setNotice({ kind: 'instance', text: labels.saved });
    } catch (reason) {
      setError({ kind: 'instance', text: reason?.message || labels.saveError });
    } finally {
      setPending('');
    }
  }

  return <>
    <View style={styles.cardGrid}>
    <View style={styles.cardColumn}><SettingsCard
      title={model.title || 'Provider credentials'}
      badge={status}
      palette={badge}
      info_label={!editable ? labels.readOnlyHelp : undefined}
      info_title={labels.readOnlyHelp}
      onInfo={!editable ? () => setHelpOpen(true) : undefined}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{labels.instanceHelp}</Text>
      {model.description ? <Text style={[styles.copy, { color: colors.textMuted }]}>{model.description}</Text> : null}
      {showKeyLink && (model.getKeyUrl || model.getKeyLabel) ? <Pressable accessibilityRole="link"
        accessibilityLabel={(model.getKeyLabel || labels.getKey).replace('{name}', model.providerLabel || 'the provider')}
        onPress={() => onOpenLink?.(model.getKeyUrl)} style={styles.linkRow}>
        <Text style={[styles.link, { color: colors.accent }]}>
          {(model.getKeyLabel || labels.getKey).replace('{name}', model.providerLabel || 'the provider')}
        </Text>
      </Pressable> : null}
      <View style={styles.fields}>
        {(model.fields || []).map(field => <FieldControl key={field.name} field={field}
          value={instanceValues[field.name]} disabled={!editable || field.disabled}
          onChange={value => setField(setInstanceValues, field.name, value)}
          colors={colors} labels={labels} />)}
      </View>
      {editable ? <View style={styles.actions}>
        <Button label={pending === 'instance' ? labels.saving : labels.save} busy={pending === 'instance'} width="full"
          disabled={Boolean(pending)} onPress={() => submit('instance')} palette={buttons} />
        {model.canClear ? <Button label={labels.remove} tone="danger-solid" width="full"
          disabled={Boolean(pending)} onPress={clear} palette={buttons} /> : null}
      </View> : <Text style={[styles.copy, { color: colors.textMuted }]}>{model.readOnlyReason || labels.fallback}</Text>}
      {editable ? <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.fallback}</Text> : null}
      {notice?.kind === 'instance' ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: colors.success }]}>{notice.text}</Text> : null}
      {error?.kind === 'instance' ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>{error.text}</Text> : null}
    </SettingsCard></View>
    {model.personalFields?.length ? <View style={styles.cardColumn}><SettingsCard title={model.personalTitle || 'Personal credentials'} palette={colors}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{labels.personalHelp}</Text>
      <View style={styles.fields}>
        {model.personalFields.map(field => <FieldControl key={field.name} field={{ ...field, label: `${labels.your || 'Your'} ${field.label}` }}
          value={personalValues[field.name]} disabled={false}
          onChange={value => setField(setPersonalValues, field.name, value)}
          colors={colors} labels={labels} />)}
      </View>
      <View style={styles.actions}>
        <Button label={pending === 'personal' ? labels.personalSaving : labels.personalSave} width="full"
          busy={pending === 'personal'} disabled={Boolean(pending)} onPress={() => submit('personal')}
          palette={buttons} />
      </View>
      {notice?.kind === 'personal' ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: colors.success }]}>{notice.text}</Text> : null}
      {error?.kind === 'personal' ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>{error.text}</Text> : null}
    </SettingsCard></View> : null}
    </View>
    <Modal transparent visible={helpOpen} animationType="fade" accessibilityViewIsModal
      onRequestClose={() => setHelpOpen(false)}>
      <View style={styles.backdrop}>
        <View style={[styles.dialog, { borderColor: colors.surfaceMuted, backgroundColor: colors.surface }]}>
          <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: colors.text }]}>{labels.readOnlyHelp}</Text>
          <Text style={[styles.copy, { color: colors.textSecondary }]}>{model.readOnlyReason}</Text>
          <Button label={labels.close} tone="surface" onPress={() => setHelpOpen(false)} palette={buttons} />
        </View>
      </View>
    </Modal>
  </>;
}

const styles = StyleSheet.create({
  cardGrid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 },
  cardColumn: { flexGrow: 1, flexBasis: 260, minWidth: 0 },
  copy: { fontSize: 12, lineHeight: 17 },
  linkRow: { alignSelf: 'flex-start' },
  link: { fontSize: 13, fontWeight: '600', textDecorationLine: 'underline' },
  fields: { gap: 12 },
  actions: { flexDirection: 'column', alignItems: 'stretch', gap: 8 },
  backdrop: { flex: 1, justifyContent: 'center', padding: 16, backgroundColor: 'rgba(0, 0, 0, 0.55)' },
  dialog: { gap: 12, borderWidth: 1, borderRadius: 10, padding: 16 },
  dialogTitle: { fontSize: 16, fontWeight: '600' },
});
