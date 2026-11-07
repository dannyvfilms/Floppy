import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { FilePicker } from '../ui/controls/FilePicker';
import { Form, useForm } from '../ui/controls/Form';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { Chip } from '../settings/Chip';
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
  link: '#818cf8',
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
  submit: 'Import',
  select: 'Select File',
  blocked: 'This import mode is not supported by this provider.',
};

const BLOCKED_MODES = ['update_collection', 'watchlist'];

function chipPalette(colors) {
  return {
    ...colors,
    badgeBorder: colors.border,
    badgeBackground: colors.surfaceStrong,
    badgeText: colors.textSecondary,
    badgeHover: colors.surfaceMuted,
    interactiveStyle: {},
    focusStyle: {},
  };
}

/**
 * The legacy page reads the live import preferences from its Alpine host. The
 * universal component receives them as a prop and keeps the same local fallback
 * and allowed-mode normalization, so the blocked state follows the card above it.
 */
function normalizedPreferences(values, model) {
  const next = { ...(values || {}) };
  if (model.allowedModes) {
    next.mode = model.allowedModes.includes(next.mode) ? next.mode : model.defaultMode;
  }
  return next;
}

function initialValues(model, preferences) {
  const values = {};
  if (model.frequency) values.frequency = model.frequency;
  (model.postFields || []).forEach(field => {
    values[field.name] = preferences[field.key] ?? '';
  });
  if (model.mediaTypes?.length && model.mediaField) values[model.mediaField] = '';
  (model.textFields || []).forEach(field => {
    values[field.name] = field.value ?? '';
  });
  return values;
}

function selectedFiles(files) {
  if (!files) return [];
  if (Array.isArray(files)) return files;
  if (typeof files.length === 'number') return Array.from(files);
  if (typeof files[Symbol.iterator] === 'function') return [...files];
  return [];
}

function fileNames(files) {
  return files.map(file => (typeof file === 'string' ? file : file?.name)).filter(Boolean).join(', ');
}

function FileImportBody({
  model,
  preferences,
  copy,
  colors,
  buttons,
  chips,
  pickFiles,
  onOpenUrl,
  onPickError,
  onSubmitError,
}) {
  const form = useForm();
  const [chosen, setChosen] = useState({});
  const files = model.files || [{
    field: model.fileField,
    accept: model.accept,
    selectLabel: model.selectLabel,
    multiple: model.multiple,
  }];
  const auto = model.autoSubmit !== false;
  const blocked = !model.allowedModes && BLOCKED_MODES.includes(preferences.mode);

  useEffect(() => {
    (model.postFields || []).forEach(field => {
      form.setValue(field.name, preferences[field.key] ?? '');
    });
  }, [form.setValue, model.postFields, preferences]);

  function submit() {
    Promise.resolve(form.submit()).catch(error => onSubmitError?.(error));
  }

  function chooseFile(file, event) {
    const picked = selectedFiles(event?.target?.files);
    if (!picked.length) return;
    setChosen(current => ({ ...current, [file.field]: fileNames(picked) }));
    form.setValue(file.field, picked);
    if (auto) submit();
  }

  return <View style={styles.body}>
    {model.oneTime && preferences.frequency !== 'once' ? <View style={styles.chipRow}>
      <Chip label={model.oneTime.label} pill palette={chips}
        accessibilityHint={model.oneTime.title} />
    </View> : null}
    <Text style={[styles.copy, { color: colors.textSecondary }]}>
      {model.sourceLabel ? <>
        {model.intro ? `${model.intro} ` : ''}
        <Text
          accessibilityRole={onOpenUrl && model.website ? 'link' : undefined}
          onPress={onOpenUrl && model.website ? () => onOpenUrl(model.website) : undefined}
          style={[styles.link, { color: colors.link }]}>{model.sourceLabel}</Text>
        . {model.description || ''}
      </> : <>
        {model.description || ''}
        {model.docs ? ' ' : ''}
        {model.docs ? <Text
          accessibilityRole={onOpenUrl && model.docs.url ? 'link' : undefined}
          onPress={onOpenUrl && model.docs.url ? () => onOpenUrl(model.docs.url) : undefined}
          style={[styles.link, { color: colors.link }]}>{model.docs.label}</Text> : null}
      </>}
    </Text>
    {model.mediaTypes?.length ? <SelectField
      id="file-import-media-type"
      name={model.mediaField}
      label={model.fieldLabel}
      value={form.values[model.mediaField] ?? ''}
      options={model.mediaTypes}
      palette={colors}
      onChange={event => form.setValue(model.mediaField, event.target.value)} /> : null}
    {model.textFields?.map(field => <TextField
      key={field.name}
      id={`file-import-${field.name}`}
      name={field.name}
      label={field.label}
      type={field.type}
      placeholder={field.placeholder}
      required={field.required}
      disabled={blocked}
      autoComplete="off"
      value={form.values[field.name] ?? ''}
      palette={colors}
      onChangeText={value => form.setValue(field.name, value)} />)}
    {model.note ? <Text style={[styles.copy, { color: colors.textMuted }]}>{model.note}</Text> : null}
    {files.map((file, index) => <View key={file.field || `file-${index}`} style={styles.fileBlock}>
      {file.label ? <Text style={[styles.copy, { color: colors.textMuted }]}>{file.label}</Text> : null}
      <FilePicker
        label={file.selectLabel || model.selectLabel || copy.select}
        accept={file.accept}
        multiple={file.multiple}
        disabled={blocked}
        pickFiles={pickFiles}
        onError={onPickError}
        palette={colors}
        onChange={event => chooseFile(file, event)} />
      {chosen[file.field] ? <Text style={[styles.copy, { color: colors.textMuted }]}>{chosen[file.field]}</Text> : null}
    </View>)}
    {!auto ? <View style={styles.actions}>
      <Button
        label={model.submitLabel || copy.submit}
        width="full"
        disabled={blocked || form.isSubmitting}
        busy={form.isSubmitting}
        onPress={submit}
        palette={buttons} />
    </View> : null}
    {blocked ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.textMuted }]}>
      {model.blockedLabel || copy.blocked}
    </Text> : null}
  </View>;
}

/**
 * Universal file-import surface for provider pages. The adapter supplies the
 * form transport (`onSubmit`), the native file picker (`pickFiles`) and URL
 * navigation; this component owns selection, preference-derived blocking and
 * the auto-submit state. `preferences` is the live `{ frequency, time, mode }`
 * object from the shared import-preferences card.
 *
 * Server model keys match the legacy island: `files`/`fileField`, `mediaTypes`,
 * `postFields`, `textFields`, `autoSubmit`, `allowedModes`/`defaultMode`.
 */
export function ProviderFileImportView({
  model = {},
  preferences: preferenceProp,
  onSubmit,
  onOpenUrl,
  onConfirm,
  pickFiles,
  onPickError,
  onSubmitError,
  palette = {},
  buttonPalette = {},
  chipPalette: chipPaletteProp = {},
  labels = {},
  title,
  testID,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const chips = { ...chipPalette(colors), ...chipPaletteProp };
  const copy = { ...defaultLabels, ...(model.labels || {}), ...labels };
  const [preferences, setPreferences] = useState(
    () => normalizedPreferences(preferenceProp ?? model.values, model),
  );

  useEffect(() => {
    if (preferenceProp === undefined) return;
    setPreferences(normalizedPreferences(preferenceProp, model));
  }, [preferenceProp, model.values, model.allowedModes, model.defaultMode]);

  const content = <Form
    id={model.id || 'file-import-form'}
    action={model.action}
    csrf={model.csrf}
    returnTo={model.next}
    encType="multipart/form-data"
    defaultValues={initialValues(model, preferences)}
    onSubmit={onSubmit}
    onConfirm={onConfirm}
    testID={testID}
    accessibilityLabel={model.formLabel || model.description}>
    <FileImportBody
      model={model}
      preferences={preferences}
      copy={copy}
      colors={colors}
      buttons={buttons}
      chips={chips}
      pickFiles={pickFiles}
      onOpenUrl={onOpenUrl}
      onPickError={onPickError}
      onSubmitError={onSubmitError} />
  </Form>;

  const heading = title || model.title;
  return heading
    ? <View style={styles.stack}><SettingsCard title={heading} palette={colors}>{content}</SettingsCard></View>
    : content;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  body: { gap: 12 },
  copy: { fontSize: 12, lineHeight: 17 },
  link: { textDecorationLine: 'underline' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  fileBlock: { gap: 6 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
