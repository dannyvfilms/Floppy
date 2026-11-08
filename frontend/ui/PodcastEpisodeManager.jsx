import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { Dialog } from './controls/Dialog';
import { FormError, FormStatus, FormTextField } from './MediaCardFormControls';

const DEFAULT_LABELS = {
  trigger: 'Manage episodes',
  title: 'Manage episodes',
  add: 'Add episode',
  edit: 'Edit',
  delete: 'Delete',
  save: 'Save',
  cancel: 'Cancel',
  close: 'Close',
  back: 'Back to episodes',
  loading: 'Loading episodes…',
  loadFailed: 'Could not load episodes.',
  retry: 'Try again',
  empty: 'No episodes yet.',
  deleteConfirm: 'Delete this episode?',
  deleteNote: 'Its play history stays in your account.',
  titleField: 'Episode title',
  descriptionField: 'Description',
  episodeNumberField: 'Episode number',
  seasonNumberField: 'Season number',
  publishedField: 'Publication date',
  durationField: 'Duration',
  durationHelp: 'Minutes, mm:ss or h:mm:ss.',
  audioField: 'Audio URL',
  websiteField: 'Website URL',
  imageField: 'Artwork URL',
  saveFailed: 'Could not save the episode.',
  deleteFailed: 'Could not delete the episode.',
};

const DEFAULT_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
};

const EMPTY_FORM = {
  title: '',
  description: '',
  episode_number: '',
  season_number: '',
  published: '',
  duration: '',
  audio_url: '',
  website_url: '',
  image: '',
};

function text(labels, key) {
  return labels[key] || DEFAULT_LABELS[key] || '';
}

function episodeFormValues(episode) {
  if (!episode) return { ...EMPTY_FORM };
  return {
    title: episode.title || '',
    description: episode.description || '',
    episode_number: episode.episodeNumber ?? '',
    season_number: episode.seasonNumber ?? '',
    published: episode.published || '',
    duration: episode.duration || '',
    audio_url: episode.audioUrl || '',
    website_url: episode.websiteUrl || '',
    image: episode.imageUrl || '',
  };
}

function episodeMeta(episode, labels) {
  const parts = [];
  if (episode.episodeNumber) {
    parts.push(`${text(labels, 'episodeNumberField')} ${episode.episodeNumber}`);
  }
  if (episode.published) parts.push(episode.published.replace('T', ' '));
  if (episode.duration) parts.push(episode.duration);
  return parts.join(' · ');
}

function ManagerForm({ values, errors, labels, palette, onChange }) {
  const fields = [
    ['title', labels.titleField, { required: true }],
    ['description', labels.descriptionField, { multiline: true }],
    ['episode_number', labels.episodeNumberField, { keyboardType: 'number-pad' }],
    ['season_number', labels.seasonNumberField, { keyboardType: 'number-pad' }],
    ['published', labels.publishedField, { placeholder: 'YYYY-MM-DDTHH:MM' }],
    ['duration', labels.durationField, { help: labels.durationHelp }],
    ['audio_url', labels.audioField, { keyboardType: 'url' }],
    ['website_url', labels.websiteField, { keyboardType: 'url' }],
    ['image', labels.imageField, { keyboardType: 'url' }],
  ];
  return <View style={styles.form}>
    {fields.map(([name, label, options]) => <FormTextField
      key={name}
      label={label}
      value={values[name]}
      onChangeText={value => onChange(name, value)}
      error={(errors[name] || []).join(' ')}
      palette={palette}
      required={Boolean(options.required)}
      multiline={Boolean(options.multiline)}
      keyboardType={options.keyboardType || 'default'}
      help={options.help}
      placeholder={options.placeholder}
      accessibilityLabel={label}
    />)}
  </View>;
}

export function PodcastEpisodeManager({
  open = false,
  status = 'idle',
  episodes = [],
  loadError = '',
  labels: suppliedLabels,
  palette: suppliedPalette,
  onOpen,
  onClose,
  onRetry,
  onSave,
  onDelete,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const [view, setView] = useState('list');
  const [editing, setEditing] = useState(null);
  const [values, setValues] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);

  function resetForm() {
    setFieldErrors({});
    setSaveError('');
    setSaving(false);
  }

  function openList() {
    setView('list');
    setEditing(null);
    resetForm();
  }

  function startAdd() {
    setEditing(null);
    setValues({ ...EMPTY_FORM });
    resetForm();
    setView('form');
  }

  function startEdit(episode) {
    setEditing(episode);
    setValues(episodeFormValues(episode));
    resetForm();
    setView('form');
  }

  function change(name, value) {
    setValues(current => ({ ...current, [name]: value }));
  }

  async function submit() {
    if (saving) return;
    setSaving(true);
    setFieldErrors({});
    setSaveError('');
    const result = await onSave?.(values, editing);
    if (!result || !result.ok) {
      setFieldErrors(result?.errors || {});
      setSaveError(result?.error || text(labels, 'saveFailed'));
      setSaving(false);
      return;
    }
    openList();
  }

  async function confirmDelete(episode) {
    if (deleting) return;
    setDeleting(true);
    setDeleteError('');
    const result = await onDelete?.(episode);
    if (!result || !result.ok) {
      setDeleteError(result?.error || text(labels, 'deleteFailed'));
      setDeleting(false);
      return;
    }
    setPendingDelete(null);
    setDeleting(false);
  }

  const actions = view === 'form' ? <View style={styles.actionRow}>
    <Button label={labels.cancel} tone="surface" palette={palette}
      disabled={saving} onPress={openList} />
    <Button label={labels.save} tone="primary" palette={palette}
      busy={saving} disabled={saving} onPress={submit} />
  </View> : <View style={styles.actionRow}>
    <Button label={labels.add} tone="primary" palette={palette} onPress={startAdd} />
  </View>;

  return <View>
    <Button label={labels.trigger} tone="primary" palette={palette} onPress={onOpen} />
    {open ? <Dialog
      open
      title={text(labels, 'title')}
      closeLabel={labels.close}
      onClose={onClose}
      palette={palette}
      actions={actions}>
      {view === 'form' ? <View style={styles.stack}>
        {saveError ? <FormError message={saveError} palette={palette} /> : null}
        <ManagerForm
          values={values}
          errors={fieldErrors}
          labels={labels}
          palette={palette}
          onChange={change}
        />
      </View> : <View style={styles.stack}>
        {status === 'loading' ? <FormStatus message={text(labels, 'loading')} tone="loading" palette={palette} /> : null}
        {status === 'error' ? <View style={styles.stack}>
          <FormError message={loadError || text(labels, 'loadFailed')} palette={palette} />
          <View style={styles.actionRow}>
            <Button label={labels.retry} tone="surface" palette={palette} onPress={onRetry} />
          </View>
        </View> : null}
        {deleteError ? <FormError message={deleteError} palette={palette} /> : null}
        {status === 'ready' ? <ScrollView keyboardShouldPersistTaps="handled" style={styles.scroll}
          contentContainerStyle={styles.stack}>
          {episodes.length === 0 ? <Text style={[styles.empty, { color: palette.textSecondary }]}>{text(labels, 'empty')}</Text> : null}
          {episodes.map(episode => <View key={episode.id}
            style={[styles.row, { backgroundColor: palette.surfaceStrong }]}>
            <View style={styles.rowBody}>
              <Text style={[styles.rowTitle, { color: palette.text }]}>{episode.title}</Text>
              <Text style={[styles.rowMeta, { color: palette.textMuted }]}>{episodeMeta(episode, labels)}</Text>
              {pendingDelete === episode.id ? <View style={styles.stack}>
                <Text style={[styles.rowMeta, { color: palette.textSecondary }]}>{text(labels, 'deleteConfirm')}</Text>
                <Text style={[styles.rowMeta, { color: palette.textMuted }]}>{text(labels, 'deleteNote')}</Text>
                <View style={styles.actionRow}>
                  <Button label={labels.cancel} tone="surface" palette={palette}
                    disabled={deleting} onPress={() => setPendingDelete(null)} />
                  <Button label={labels.delete} tone="danger-solid" palette={palette}
                    busy={deleting} disabled={deleting} onPress={() => confirmDelete(episode)} />
                </View>
              </View> : null}
            </View>
            {pendingDelete === episode.id ? null : <View style={styles.rowActions}>
              <Pressable accessibilityRole="button" accessibilityLabel={`${labels.edit} ${episode.title}`}
                onPress={() => startEdit(episode)} style={styles.textButton}>
                <Text style={[styles.textButtonLabel, { color: palette.accent }]}>{labels.edit}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={`${labels.delete} ${episode.title}`}
                onPress={() => { setPendingDelete(episode.id); setDeleteError(''); }} style={styles.textButton}>
                <Text style={[styles.textButtonLabel, { color: palette.danger }]}>{labels.delete}</Text>
              </Pressable>
            </View>}
          </View>)}
        </ScrollView> : null}
      </View>}
    </Dialog> : null}
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  form: { gap: 12 },
  scroll: { flexGrow: 0 },
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
    borderRadius: 6,
    padding: 12,
  },
  rowBody: { flexShrink: 1, minWidth: 0, gap: 2 },
  rowTitle: { fontSize: 15, fontWeight: '600' },
  rowMeta: { fontSize: 13, lineHeight: 18 },
  rowActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  textButton: { paddingVertical: 4, paddingHorizontal: 2 },
  textButtonLabel: { fontSize: 13, fontWeight: '600' },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8 },
  empty: { fontSize: 13, paddingVertical: 8 },
});
