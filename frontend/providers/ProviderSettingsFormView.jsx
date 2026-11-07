import React, { useEffect, useState } from 'react';
import { StyleSheet, Switch, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { Form, useForm } from '../ui/controls/Form';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { SettingsCard } from '../settings/SettingsCard';

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
  danger: '#ef4444',
  success: '#10b981',
  warning: '#f59e0b',
  radius: 6,
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const defaultLabels = {
  submit: 'Save Changes',
  blocked: 'This import mode is not supported by this provider.',
};

const BLOCKED_MODES = ['update_collection', 'watchlist'];

function initialValue(field) {
  if (field.type === 'toggle') return Boolean(field.value);
  return field.value ?? '';
}

function initialValues(form, mode) {
  const values = {};
  Object.entries(form.hidden || {}).forEach(([name, value]) => {
    values[name] = value ?? '';
  });
  if (Object.prototype.hasOwnProperty.call(values, 'mode')) values.mode = mode ?? '';
  (form.fields || []).forEach(field => {
    values[field.name] = initialValue(field);
  });
  return values;
}

// An unchecked browser checkbox is not posted at all. The universal form keeps
// booleans, so remove false toggle values to preserve the legacy POST shape.
function submittedValues(values, fields) {
  const next = { ...values };
  (fields || []).forEach(field => {
    if (field.showWhen && values[field.showWhen.name] === field.showWhen.not) {
      delete next[field.name];
    } else if (field.type === 'toggle' && !next[field.name]) {
      delete next[field.name];
    }
  });
  return next;
}

function SwitchField({ id, field, checked, onChange, colors }) {
  const tone = field.tone === 'warning' ? colors.warning : field.tone === 'danger' ? colors.danger : colors.text;
  return <View style={[styles.toggleRow, { backgroundColor: colors.surfaceStrong, opacity: field.disabled ? 0.5 : 1 }]}>
    <View style={styles.toggleCopy}>
      <Text style={[styles.toggleLabel, { color: tone }]}>{field.label}</Text>
      {field.help ? <Text style={[styles.help, { color: colors.textMuted }]}>{field.help}</Text> : null}
    </View>
    <Switch
      nativeID={id}
      accessibilityLabel={field.label}
      accessibilityHint={field.help}
      accessibilityState={{ disabled: Boolean(field.disabled) }}
      disabled={Boolean(field.disabled)}
      value={checked}
      onValueChange={onChange}
      trackColor={{ false: colors.surfaceMuted, true: colors.accentStrong }}
      thumbColor={colors.text} />
  </View>;
}

function SettingsFormField({ field, formId, values, setValue, colors }) {
  const id = `${formId}-${field.name}`;
  if (field.showWhen && values[field.showWhen.name] === field.showWhen.not) return null;
  if (field.type === 'toggle') {
    return <SwitchField id={id} field={field} checked={Boolean(values[field.name])}
      onChange={next => setValue(field.name, next)} colors={colors} />;
  }
  if (field.type === 'select') {
    return <SelectField id={id} name={field.name} label={field.label}
      value={values[field.name] ?? ''} options={field.options || []}
      help={field.help} disabled={field.disabled} palette={colors}
      onChange={event => setValue(field.name, event.target.value)} />;
  }
  return <TextField id={id} name={field.name} label={field.label} type={field.type || 'text'}
    placeholder={field.placeholder} required={field.required} disabled={field.disabled}
    autoComplete={field.autoComplete || 'off'} maxLength={field.attrs?.maxLength}
    value={values[field.name] ?? ''} help={field.help} palette={colors}
    onChangeText={next => setValue(field.name, next)} />;
}

function SettingsFormBody({ form, mode, blocked, copy, colors, buttons, onSubmitError }) {
  const runtime = useForm();
  const fields = form.fields || [];
  const hasHiddenMode = Object.prototype.hasOwnProperty.call(form.hidden || {}, 'mode');

  useEffect(() => {
    if (hasHiddenMode && runtime.getValue('mode') !== mode) {
      runtime.setValue('mode', mode);
    }
  }, [hasHiddenMode, mode, runtime.getValue, runtime.setValue]);

  function submit() {
    Promise.resolve(runtime.submit()).catch(error => onSubmitError?.(error));
  }

  return <View style={styles.body}>
    {form.intro ? <Text style={[styles.copy, { color: colors.textSecondary }]}>{form.intro}</Text> : null}
    {fields.map(field => <SettingsFormField key={field.name} field={field} formId={form.id}
      values={runtime.values} setValue={runtime.setValue} colors={colors} />)}
    <View style={styles.actions}>
      <Button label={form.submit || copy.submit} width="full" disabled={blocked || runtime.isSubmitting}
        busy={runtime.isSubmitting} onPress={submit} palette={buttons} />
    </View>
    {blocked ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.textMuted }]}>
      {form.blockedLabel || copy.blocked}
    </Text> : null}
  </View>;
}

/**
 * Universal provider settings form. It preserves the legacy dynamic-field
 * contract: `showWhen` hides a field when another value matches `not`, toggle
 * fields render as switches, and forms that follow the page import preferences
 * post the live mode and block when that mode cannot be imported.
 *
 * The adapter owns transport through `onSubmit({ action, csrf, returnTo, values,
 * event })`; `preferences` supplies the live import preferences object. Text,
 * select and toggle values are collected by the shared Form contract.
 */
export function ProviderSettingsFormView({
  form = {},
  preferences,
  onSubmit,
  onConfirm,
  onSubmitError,
  palette = {},
  buttonPalette = {},
  labels = {},
  title,
  testID,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...(form.labels || {}), ...labels };
  const [mode, setMode] = useState(() => (
    form.followPreferences ? (preferences?.mode ?? form.hidden?.mode) : form.hidden?.mode
  ));

  useEffect(() => {
    if (!form.followPreferences || preferences?.mode === undefined) return;
    setMode(preferences.mode);
  }, [form.followPreferences, preferences?.mode]);

  const blocked = Boolean(form.followPreferences && BLOCKED_MODES.includes(mode));
  const handleSubmit = onSubmit
    ? payload => onSubmit({ ...payload, values: submittedValues(payload.values, form.fields) })
    : undefined;
  const content = <Form
    key={form.id}
    id={form.id}
    action={form.action}
    csrf={form.csrf}
    returnTo={form.next}
    defaultValues={initialValues(form, mode)}
    onSubmit={handleSubmit}
    onConfirm={onConfirm}
    testID={testID}
    accessibilityLabel={form.intro}>
    <SettingsFormBody form={form} mode={mode} blocked={blocked}
      copy={copy} colors={colors} buttons={buttons} onSubmitError={onSubmitError} />
  </Form>;

  const heading = title || form.title;
  return heading
    ? <View style={styles.stack}><SettingsCard title={heading} palette={colors}>{content}</SettingsCard></View>
    : content;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  body: { gap: 12 },
  copy: { fontSize: 12, lineHeight: 17 },
  help: { fontSize: 12, lineHeight: 17 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 8, padding: 10 },
  toggleCopy: { flex: 1, minWidth: 0, gap: 2 },
  toggleLabel: { fontSize: 14, fontWeight: '600' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
