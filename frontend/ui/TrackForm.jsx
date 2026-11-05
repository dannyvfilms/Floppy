import React, { useState } from 'react';
import { ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { DateTimePicker } from './DateTimePicker';
import {
  FormError,
  FormField,
  FormHeader,
  FormSelect,
  FormStatus,
  FormTextField,
} from './MediaCardFormControls';
import { TrackTabs } from './TrackFormTabs';
import { validateTrackValues } from './mediaCardForms';

const DEFAULT_LABELS = {
  title: 'Tracking',
  close: 'Close',
  loading: 'Loading',
  loadFailed: "Couldn't load this form.",
  retry: 'Try again',
  save: 'Save',
  saving: 'Saving',
  delete: 'Delete',
  required: '%s is required.',
  invalidNumber: 'Enter a number.',
  minimum: 'Must be at least %s.',
  maximum: 'Must be at most %s.',
  dateOrder: 'End date must be on or after the start date.',
  dateTime: {},
};

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
  dateTime: {},
};

function fieldType(field) {
  if (field.options?.length) return 'select';
  if (field.type === 'date' || field.name === 'start_date' || field.name === 'end_date') return 'date';
  if (field.type === 'textarea') return 'textarea';
  if (field.type === 'number') return 'number';
  return 'text';
}

export function TrackForm({
  model,
  values = {},
  errors = {},
  status = 'ready',
  serverError = '',
  busy = false,
  labels: suppliedLabels,
  palette: suppliedPalette,
  onChange,
  onSubmit,
  onDelete,
  onRetry,
  onClose,
  showHeader = true,
  closeRef,
  nativeID,
  tabs = [],
  activeTab,
  onTabChange,
  onRetryTabs,
  onTagToggle,
  onTagCreate,
  onArtworkSave,
  onDiscoverToggle,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const { height } = useWindowDimensions();
  const [localErrors, setLocalErrors] = useState({});
  const [localTab, setLocalTab] = useState('general');
  const fieldErrors = { ...errors, ...localErrors };
  const selectedTab = activeTab === undefined ? localTab : activeTab;

  function selectTab(id) {
    if (activeTab === undefined) setLocalTab(id);
    onTabChange?.(id);
  }

  function change(name, value) {
    if (localErrors[name]) setLocalErrors(current => ({ ...current, [name]: '' }));
    onChange?.(name, value);
  }

  function submit() {
    const next = validateTrackValues(model, values, labels);
    setLocalErrors(next);
    if (Object.keys(next).length) return;
    onSubmit?.(values);
  }

  const generalBody = <View style={styles.stack}>
    {model?.fields.filter(field => field.name !== 'notes').map(field => {
      const type = fieldType(field);
      const value = values[field.name] == null ? '' : values[field.name];
      if (type === 'select') {
        return <FormSelect key={field.name} label={field.label} value={value}
          options={field.options} required={field.required} help={field.help}
          error={fieldErrors[field.name]} palette={palette}
          onChange={next => change(field.name, next)} />;
      }
      if (type === 'date') {
        return <FormField key={field.name} label={field.label} required={field.required}
          help={field.help} error={fieldErrors[field.name]} palette={palette}>
          <DateTimePicker value={value} onChange={next => change(field.name, next)}
            trackTime={Boolean(model.trackTime)} labels={labels.dateTime || {}}
            palette={palette.dateTime || {}} />
        </FormField>;
      }
      return <FormTextField key={field.name} label={field.label} value={value}
        onChangeText={next => change(field.name, next)} required={field.required}
        help={field.help} error={fieldErrors[field.name]} placeholder={field.placeholder}
        keyboardType={type === 'number' ? 'numeric' : 'default'}
        multiline={type === 'textarea'} palette={palette} />;
    })}
    {model?.fields.filter(field => field.name === 'notes').map(field => <FormTextField
      key={field.name} label={field.label} value={values[field.name] == null ? '' : values[field.name]}
      onChangeText={next => change(field.name, next)} help={field.help}
      error={fieldErrors[field.name]} multiline palette={palette} />)}
    <View style={styles.actions}>
      <Button label={busy ? labels.saving : (model?.submitLabel || labels.save)} busy={busy} disabled={busy}
        onPress={submit} palette={palette} />
      {model?.deleteAction && onDelete ? <Button label={labels.delete} tone="danger-solid"
        disabled={busy} onPress={() => onDelete(values)} palette={palette} /> : null}
    </View>
  </View>;

  return <View nativeID={nativeID} style={[styles.card, { backgroundColor: palette.surface, maxHeight: height * 0.88 }]}>
    {showHeader ? <FormHeader title={model?.title || labels.title} closeLabel={labels.close}
      onClose={onClose} closeRef={closeRef} palette={palette} /> : null}
    {status === 'loading' ? <FormStatus message={labels.loading} tone="loading" palette={palette} /> : null}
    {status === 'error' ? <View style={styles.stack}>
      <FormError message={labels.loadFailed} palette={palette} />
      <Button label={labels.retry} tone="surface" onPress={onRetry} palette={palette} />
    </View> : null}
    {status === 'ready' && model ? <ScrollView keyboardShouldPersistTaps="handled" style={styles.scroll}
      contentContainerStyle={styles.stack}>
      {model.subtitle ? <View style={styles.subtitleWrap}>
        <FormStatus message={model.subtitle} palette={palette} />
      </View> : null}
      {serverError ? <FormError message={serverError} palette={palette} /> : null}
      {tabs.length ? <TrackTabs tabs={tabs} activeId={selectedTab} onChange={selectTab}
        labels={labels} palette={palette} generalContent={generalBody}
        onRetry={onRetryTabs} onTagToggle={onTagToggle} onTagCreate={onTagCreate}
        onArtworkSave={onArtworkSave} onDiscoverToggle={onDiscoverToggle} /> : generalBody}
    </ScrollView> : null}
  </View>;
}

const styles = StyleSheet.create({
  card: {
    width: '100%', borderRadius: 8, padding: 24, gap: 16,
    shadowColor: '#000000', shadowOpacity: 0.35, shadowRadius: 24, shadowOffset: { width: 0, height: 12 }, elevation: 16,
  },
  scroll: { flexGrow: 0 },
  stack: { gap: 14 },
  subtitleWrap: { marginTop: -4 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginTop: 4 },
});
