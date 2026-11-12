import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { FormSaveBar } from './FormSaveBar';
import { SelectField } from './SelectField';
import { ToggleChip } from './ToggleChip';

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
  accentText: '#ffffff',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const defaultLabels = {
  save: 'Save Preferences',
  saving: 'Saving…',
  savedTitle: 'All changes saved',
  savedCopy: 'Your preferences are up to date.',
  dirtyTitle: 'Unsaved changes',
  dirtyCopy: 'Save your preferences to keep your changes.',
  savingTitle: 'Saving changes',
  savingCopy: 'Applying your preferences…',
  errorTitle: 'Could not save changes',
  saveError: 'Check the highlighted fields and try again.',
  validationError: 'Some preferences still need attention.',
  addRule: 'Add auto-pause rule',
  addAnotherRule: 'Enabled. Click to add additional rule.',
  removeRule: 'Remove',
  noRules: 'No auto-pause rules yet. Add one to get started.',
  weeks: 'weeks',
  allLibraries: 'All Libraries',
  library: 'Library',
  closeOptions: 'Close options',
};

function sameValues(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function AutoPauseField({ field, rules, disabled, error, palette, buttonPalette, labels, onChange }) {
  const colors = { ...defaultPalette, ...palette };
  const libraryOptions = field.options || [];
  function update(index, changes) {
    onChange(rules.map((rule, position) => position === index ? { ...rule, ...changes } : rule));
  }
  function add() {
    if (disabled) return;
    onChange([...rules, {
      library: field.defaultLibrary || 'all',
      weeks: field.defaultWeeks || 16,
    }]);
  }
  function remove(index) {
    if (disabled) return;
    onChange(rules.filter((_, position) => position !== index));
  }
  function libraryLabel(value) {
    return libraryOptions.find(option => option.value === value)?.label || labels.allLibraries;
  }
  return <View style={styles.autoPause}>
    <View style={[styles.autoPauseHeading, colors.preferenceCards && { flexDirection: 'row', gap: 12, alignItems: 'flex-start' }]}>
      <Text style={[styles.label, { color: colors.textMuted }, colors.preferenceCards && { fontSize: 14, lineHeight: 20, flex: 1 }]}>{field.label}</Text>
      {field.help ? <Text style={[styles.help, { color: colors.textMuted }, colors.preferenceCards && { flex: 1, textAlign: 'right' }]}>{field.help}</Text> : null}
    </View>
    {colors.preferenceCards ? <Pressable accessibilityRole="button" disabled={disabled} onPress={add}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 9,
        borderWidth: 1, borderRadius: colors.radius, borderColor: colors.fieldBorder || colors.border, backgroundColor: colors.surface }}>
      <Text style={{ flex: 1, color: colors.textSecondary, fontSize: 14, lineHeight: 20, textAlign: 'center' }}>{rules.length ? (field.addAnotherLabel || labels.addAnotherRule) : (field.addLabel || labels.addRule)}</Text>
      <Icon spec={actionIcons.chevronDown} color={colors.textMuted} size={16} />
    </Pressable> : <Button
      label={rules.length ? (field.addAnotherLabel || labels.addAnotherRule) : (field.addLabel || labels.addRule)}
      tone="surface"
      disabled={disabled}
      onPress={add}
      palette={{ ...defaultButtonPalette, ...buttonPalette }}
    />}
    {error ? <Text accessibilityRole="alert" style={[styles.help, { color: colors.danger }]}>{error}</Text> : null}
    {rules.length === 0 && !colors.preferenceCards ? <Text style={[styles.help, { color: colors.textMuted }]}>{field.emptyLabel || labels.noRules}</Text> : null}
    {rules.map((rule, index) => <View key={`rule-${index}`} style={[styles.rule, { borderColor: colors.border, backgroundColor: colors.background }, colors.preferenceCards && { borderWidth: 0, padding: 0, backgroundColor: 'transparent' }]}>
      <SelectField
        label={`${field.libraryLabel || labels.library} ${index + 1}`}
        labelHidden={Boolean(colors.preferenceCards)} iconChevron={Boolean(colors.preferenceCards)}
        id={`${field.name}-library-${index}`}
        options={libraryOptions}
        value={rule.library}
        disabled={disabled}
        palette={palette}
        onChange={event => update(index, { library: event.target.value })}
      />
      <View style={styles.weeksRow}>
        <TextInput
          accessibilityLabel={`${field.weeksLabel || labels.weeks} ${labelForRule(index, rule, libraryOptions, labels)}`}
          value={String(rule.weeks ?? '')}
          editable={!disabled}
          keyboardType="number-pad"
          maxLength={3}
          onChangeText={text => update(index, { weeks: Number(text.replace(/[^0-9]/g, '')) })}
          style={[styles.input, {
            borderColor: colors.border,
            backgroundColor: colors.surface,
            color: colors.textSecondary,
            opacity: disabled ? 0.5 : 1,
          }]}
        />
        <Text style={[styles.weeks, { color: colors.textMuted }]}>{field.weeksLabel || labels.weeks}</Text>
      </View>
      <Button label={field.removeLabel || labels.removeRule} tone="danger-solid"
        disabled={disabled} onPress={() => remove(index)} palette={{ ...defaultButtonPalette, ...buttonPalette }} />
    </View>)}
  </View>;
}

function labelForRule(index, rule, options, labels) {
  return options.find(option => option.value === rule.library)?.label || `${labels.allLibraries} ${index + 1}`;
}

/**
 * Shared preferences presentation. Fields are described by data; the caller owns
 * values, persistence and any server-side validation result.
 */
export function PreferencesForm({
  SaveBar = FormSaveBar,
  sections = [],
  values = {},
  initialValues = {},
  onChange,
  onSave,
  validate,
  labels,
  palette = {},
  buttonPalette = {},
  disabled = false,
  csrf,
  fieldErrors = {},
  formError,
  onSectionLink,
}) {
  const copy = { ...defaultLabels, ...labels };
  const colors = { ...defaultPalette, ...palette };
  const [saving, setSaving] = useState(false);
  const [localErrors, setLocalErrors] = useState({});
  const [localError, setLocalError] = useState('');
  const serialized = useMemo(() => JSON.stringify(values), [values]);
  const dirty = useMemo(() => !sameValues(values, initialValues), [values, initialValues]);
  const errors = { ...localErrors, ...fieldErrors };
  const error = localError || formError || '';

  useEffect(() => {
    setLocalError('');
    setLocalErrors({});
  }, [serialized]);

  async function save() {
    if (saving || disabled) return;
    const problems = validate ? validate(values) : {};
    if (problems && Object.keys(problems).length) {
      setLocalErrors(problems);
      setLocalError(copy.validationError);
      return;
    }
    setLocalErrors({});
    setLocalError('');
    setSaving(true);
    try {
      await onSave?.({ values, csrf });
    } catch (reason) {
      setLocalError(reason?.message || copy.saveError);
    } finally {
      setSaving(false);
    }
  }

  function renderField(field) {
    const fieldDisabled = disabled || field.disabled;
    if (field.type === 'toggle') {
      if (colors.preferenceCards) return <SelectField key={field.name}
        label={field.label} help={field.help} value={String(Boolean(values[field.name]))}
        options={[{ value: 'false', label: field.offLabel || 'Disabled' }, { value: 'true', label: field.onLabel || 'Enabled' }]}
        disabled={fieldDisabled} palette={colors} iconChevron
        onChange={event => onChange?.(field.name, event.target.value === 'true')} />;
      return <ToggleChip
        key={field.name}
        value={Boolean(values[field.name])}
        disabled={fieldDisabled}
        label={field.label}
        help={field.help}
        offLabel={field.offLabel}
        onLabel={field.onLabel}
        palette={colors}
        onChange={next => onChange?.(field.name, next)}
      />;
    }
    if (field.type === 'autoPause') {
      return <AutoPauseField
        key={field.name}
        field={field}
        rules={values[field.name] || []}
        disabled={fieldDisabled}
        error={errors[field.name]}
        palette={colors}
        buttonPalette={buttonPalette}
        labels={copy}
        onChange={next => onChange?.(field.name, next)}
      />;
    }
    return <SelectField
      key={field.name}
      id={field.name}
      name={field.name}
      label={field.label}
      help={field.help}
      options={field.options || []}
      placeholder={field.placeholder}
      value={values[field.name]}
      disabled={fieldDisabled}
      error={errors[field.name]}
      palette={colors}
      iconChevron={Boolean(colors.preferenceCards)}
      onChange={event => onChange?.(field.name, event.target.value)}
    />;
  }

  return <View style={styles.form}>
    {sections.map(section => <View key={section.id} style={[styles.section, colors.preferenceCards && { padding: 16, borderRadius: 8, backgroundColor: colors.surface, gap: 16 }]}>
      <View style={[styles.sectionHeading, colors.preferenceCards && { flexDirection: 'row', gap: 12, marginTop: 2 }]}>
        {section.icon && colors.preferenceCards ? <View style={{ width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: 6, overflow: 'hidden' }}>
          <View style={[StyleSheet.absoluteFillObject, { backgroundColor: colors.accent, opacity: 0.12 }]} />
          <Icon spec={section.icon} color={colors.link || colors.accent} size={20} />
        </View> : null}
        <View style={{ gap: 4, flex: 1 }}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: colors.text }]}>{section.title}</Text>
        {section.copy ? <Text style={[styles.help, { color: colors.textMuted }]}>{section.copy}</Text> : null}
        </View>
      </View>
      <View style={[styles.fields, colors.preferenceCards && { gap: 12 }]}>{section.fields.map(field => colors.preferenceCards
        ? <React.Fragment key={field.name}>
          <View style={{ padding: 12.8, borderRadius: 6, backgroundColor: colors.surfaceStrong }}>{renderField(field)}</View>
          {section.footerAfter === field.name && section.footer && onSectionLink ? <Pressable accessibilityRole="link" onPress={() => onSectionLink(section.id)}>
            <Text style={[styles.help, { color: colors.link }]}>{section.footer}</Text>
          </Pressable> : null}
        </React.Fragment>
        : renderField(field))}</View>
      {section.footer && !section.footerAfter && onSectionLink ? <Pressable accessibilityRole="link" onPress={() => onSectionLink(section.id)}>
        <Text style={[styles.help, { color: colors.link }]}>{section.footer}</Text>
      </Pressable> : null}
    </View>)}
    <SaveBar
      dirty={dirty}
      saving={saving}
      disabled={disabled}
      error={error}
      onSave={save}
      labels={copy}
      palette={colors}
      buttonPalette={{ ...defaultButtonPalette, ...buttonPalette }}
    />
  </View>;
}

const styles = StyleSheet.create({
  form: { gap: 20 },
  section: { gap: 12 },
  sectionHeading: { gap: 2 },
  sectionTitle: { fontSize: 15, fontWeight: '700' },
  fields: { gap: 14 },
  label: { fontSize: 12, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  autoPause: { gap: 10 },
  autoPauseHeading: { gap: 2 },
  rule: { gap: 10, borderWidth: 1, borderRadius: 8, padding: 10 },
  weeksRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  input: { flex: 1, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, fontSize: 14 },
  weeks: { fontSize: 12 },
});
