import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { TrackDialog } from '../../../frontend/ui/TrackDialog';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'TRACKING',
  status: 'in_progress',
  title: 'Detail tracking and edit dialogs',
  where: 'Detail actions, episode and issue rows',
  note: 'The General, Tags, Metadata, Collection, Episode plays and Status history tracking tabs run on the shared TrackForm and TrackDialog with demo detail data. Date/status/progress coupling, notes, delete, repeat identity, validation, busy and error states are presentation-owned by the shared dialog. The web detail pages keep their server-rendered htmx and OOB save path, permissions and progressive fallback.',
};

const trackLabels = {
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
  general: 'General',
  tags: 'Tags',
  noTags: 'No tags yet. Create one below.',
  newTag: 'New tag...',
  addTag: 'Add',
  add: 'Add',
  remove: 'Remove',
  tagFailed: "Couldn't update this tag.",
  metadata: 'Metadata',
  artwork: 'Artwork URL',
  saveArtwork: 'Save artwork',
  artworkFailed: "Couldn't save the artwork.",
  artworkUnavailable: 'Save this item before changing its artwork.',
  collection: 'Collection',
  noCollection: 'No owned copies recorded.',
  plays: 'Episode plays',
  noPlays: 'No plays recorded yet.',
  statusHistory: 'Status history',
  noStatusChanges: 'No status changes recorded yet.',
  noStatus: 'No Status',
  sourceNotRecorded: 'source not recorded',
  dateTime: {},
};

const formPalette = {
  ...palette,
  textSecondary: palette.textSecondary,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  accent: palette.accent,
  accentContrast: '#ffffff',
  danger: palette.danger,
  radius: radius.md,
  focusStyle: {},
  backdrop: 'rgba(0, 0, 0, 0.65)',
  dateTime: {
    text: palette.text,
    textSecondary: palette.textSecondary,
    textMuted: palette.textMuted,
    surface: palette.surface,
    surfaceStrong: palette.surfaceStrong,
    surfaceMuted: palette.surfaceMuted,
    border: palette.border,
    accent: palette.accent,
    accentContrast: '#ffffff',
    link: '#818cf8',
    danger: palette.danger,
    radius: radius.md,
    radiusSmall: radius.sm,
  },
  rating: {
    lit: palette.warning,
    unlit: palette.surfaceMuted,
    muted: palette.textMuted,
    focusStyle: {},
  },
};

const buttonPalette = {
  radius: radius.sm,
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(239, 68, 68, 0.2)', hovered: 'rgba(239, 68, 68, 0.2)', text: palette.danger, border: 'transparent' },
  focusStyle: {},
};

const statusOptions = [
  { value: 'Planning', label: 'Planning' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Dropped', label: 'Dropped' },
];

const showModel = {
  title: 'Tracking',
  subtitle: 'The Quiet Orbit · Show',
  formId: 'detail-show-track',
  instanceId: 'show-1',
  isNew: false,
  mediaType: 'tv',
  submitLabel: 'Update',
  deleteAction: '/demo/detail/track/delete',
  trackTime: false,
  fields: [
    { name: 'status', label: 'Status', type: 'select', value: 'In progress', required: true, options: statusOptions },
    { name: 'score', label: 'Score', type: 'rating', value: '8', max: 10 },
    { name: 'progress', label: 'Progress', type: 'number', value: '6', min: 0, max: 10, help: 'Episodes watched' },
    { name: 'start_date', label: 'Start date', type: 'date', value: '2026-10-01' },
    { name: 'end_date', label: 'End date', type: 'date', value: '' },
    { name: 'entry_source', label: 'Source', type: 'text', value: 'tmdb', placeholder: 'Where this entry came from' },
    { name: 'notes', label: 'Notes', type: 'textarea', value: 'Watching with the family.\nThe relay arc holds up on a rewatch.' },
  ],
  repeatIdentity: {
    rewatchLabel: 'Start rewatch',
    rewatchAction: 'start',
  },
};

function episodeModel(target) {
  const item = target?.item || {};
  const existing = Boolean(item.historyRows?.length);
  return {
    title: item.title || 'Track episode',
    subtitle: `The Quiet Orbit · ${item.code || 'Episode'}`,
    formId: `detail-episode-track-${item.key || 'episode'}`,
    instanceId: existing ? `${item.key || 'episode'}-play` : '',
    isNew: !existing,
    mediaType: 'episode',
    submitLabel: existing ? 'Update' : 'Add',
    deleteAction: existing ? `/demo/detail/episode/${item.key || 'episode'}/delete` : '',
    trackTime: false,
    fields: [
      { name: 'status', label: 'Status', type: 'select', value: 'Completed', required: true, options: statusOptions.slice(1, 2).concat(statusOptions.slice(3, 4)) },
      { name: 'score', label: 'Score', type: 'rating', value: item.score == null ? '' : String(item.score), max: 10 },
      { name: 'start_date', label: 'Start date', type: 'date', value: item.dateValue || '2024-10-04' },
      { name: 'end_date', label: 'End date', type: 'date', value: item.dateValue || '2024-10-04' },
      { name: 'entry_source', label: 'Source', type: 'text', value: 'tmdb', placeholder: 'Where this entry came from' },
      { name: 'notes', label: 'Notes', type: 'textarea', value: item.historyRows?.[0]?.note || '' },
    ],
    repeatIdentity: existing ? {
      canSaveAsNew: true,
      saveAsNewLabel: 'Save as new entry',
    } : {},
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function initialValues(model) {
  return Object.fromEntries((model?.fields || []).map(field => [field.name, field.value ?? '']));
}

function demoTabs() {
  return [
    {
      id: 'tags',
      label: 'Tags',
      kind: 'tags',
      status: 'ready',
      error: '',
      tags: [
        { id: 'comfort', name: 'Comfort watches', hasTag: true, pending: false, error: '' },
        { id: 'sci-fi', name: 'Sci-fi', hasTag: false, pending: false, error: '' },
        { id: 'family', name: 'Family', hasTag: false, pending: false, error: '' },
      ],
    },
    {
      id: 'metadata',
      label: 'Metadata',
      kind: 'metadata',
      status: 'ready',
      error: '',
      fields: [
        { label: 'Title', value: 'The Quiet Orbit' },
        { label: 'Media type', value: 'TV show' },
        { label: 'Provider', value: 'tmdb' },
        { label: 'Provider id', value: '76479' },
        { label: 'Release', value: '2024-02-09' },
        { label: 'Genres', value: 'Science Fiction, Drama' },
        { label: 'Provider score', value: '8.1' },
      ],
      imageUrl: 'https://picsum.photos/seed/floppy-orbit/400/600',
      canEditArtwork: true,
      itemId: 'demo-orbit',
    },
    {
      id: 'collection',
      label: 'Collection',
      kind: 'collection',
      status: 'ready',
      error: '',
      entries: [
        { id: 'copy-1', title: 'The Quiet Orbit', detail: 'Blu-ray · 1080p · HDR10', date: '2025-03-14' },
        { id: 'copy-2', title: 'The Quiet Orbit', detail: 'Digital · 4K', date: '2025-02-02' },
      ],
    },
    {
      id: 'plays',
      label: 'Episode plays',
      kind: 'plays',
      status: 'ready',
      error: '',
      entries: [
        { id: 'play-1', title: 'In progress', detail: 'Episode 7 · The Outer Ring', date: '2026-10-12' },
        { id: 'play-2', title: 'Completed', detail: 'Episode 6 · Halcyon', date: '2026-10-08' },
      ],
    },
    {
      id: 'status-history',
      label: 'Status history',
      kind: 'status-history',
      status: 'ready',
      error: '',
      changes: [
        { id: 'change-1', old: 'Planning', next: 'In progress', date: 'Oct 2, 2026', reason: 'manual' },
        { id: 'change-2', old: 'In progress', next: 'Paused', date: 'Sep 18, 2026', reason: 'webhook' },
        { id: 'change-3', old: 'Paused', next: 'In progress', date: 'Sep 16, 2026', reason: 'manual' },
      ],
    },
  ];
}

function createSession(target) {
  if (!target) return null;
  const model = target.kind === 'episode' || target.kind === 'issue'
    ? episodeModel(target)
    : clone(showModel);
  return {
    model,
    values: initialValues(model),
    tabs: demoTabs(),
    status: 'ready',
    busy: false,
    errors: {},
    serverError: '',
  };
}

function updateTab(tabs, id, update) {
  return tabs.map(tab => tab.id === id ? update(tab) : tab);
}

function delay(ms = 350) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function DetailTrackingSlot({ target, onOpen, onClose }) {
  const targetKey = target ? `${target.kind}:${target.item?.key || 'item'}` : '';
  const [session, setSession] = useState(null);
  const [result, setResult] = useState('');

  useEffect(() => {
    setSession(createSession(target));
  }, [targetKey]);

  function close(message) {
    if (message) setResult(message);
    onClose?.();
  }

  function updateValue(name, value) {
    setSession(current => current ? {
      ...current,
      values: { ...current.values, [name]: value },
      errors: { ...current.errors, [name]: '' },
    } : current);
  }

  async function submit(values) {
    setSession(current => current ? { ...current, busy: true, serverError: '' } : current);
    await delay();
    const saved = target?.kind === 'episode' || target?.kind === 'issue'
      ? `${target.item?.title || 'Episode'} saved.`
      : 'Tracking entry saved.';
    setSession(current => current ? { ...current, busy: false } : current);
    close(saved);
  }

  async function saveAsNew(values) {
    setSession(current => current ? { ...current, busy: true } : current);
    await delay();
    setSession(current => current ? { ...current, busy: false } : current);
    close(`Saved ${target?.item?.title || 'episode'} as a new entry.`);
  }

  function toggleRewatch(action, values) {
    const started = action !== 'stop';
    setSession(current => {
      if (!current) return current;
      return {
        ...current,
        model: {
          ...current.model,
          repeatIdentity: {
            ...current.model.repeatIdentity,
            rewatchLabel: started ? 'End rewatch' : 'Start rewatch',
            rewatchAction: started ? 'stop' : 'start',
            rewatchStartedAt: started ? '2026-11-04' : '',
          },
        },
        values: {
          ...current.values,
          ...(started ? { status: 'In progress', end_date: '' } : { status: 'Completed', end_date: '2026-11-04' }),
        },
      };
    });
    setResult(started ? 'Rewatch started from today.' : 'Rewatch ended.');
  }

  async function remove() {
    setSession(current => current ? { ...current, busy: true } : current);
    await delay();
    setSession(current => current ? { ...current, busy: false } : current);
    close('Entry deleted.');
  }

  async function retryTabs() {
    setSession(current => current ? { ...current, tabs: demoTabs() } : current);
  }

  async function toggleTag(tag) {
    setSession(current => current ? {
      ...current,
      tabs: updateTab(current.tabs, 'tags', tab => ({
        ...tab,
        tags: tab.tags.map(entry => entry.id === tag.id ? { ...entry, pending: true, error: '' } : entry),
      })),
    } : current);
    await delay(200);
    setSession(current => current ? {
      ...current,
      tabs: updateTab(current.tabs, 'tags', tab => ({
        ...tab,
        tags: tab.tags.map(entry => entry.id === tag.id ? { ...entry, hasTag: !tag.hasTag, pending: false } : entry),
      })),
    } : current);
  }

  async function addTag(name) {
    await delay(200);
    setSession(current => current ? {
      ...current,
      tabs: updateTab(current.tabs, 'tags', tab => ({
        ...tab,
        tags: [...(tab.tags || []), { id: `tag-${name}`, name, hasTag: true, pending: false, error: '' }],
      })),
    } : current);
  }

  async function saveArtwork(imageUrl) {
    await delay(200);
    setSession(current => current ? {
      ...current,
      tabs: updateTab(current.tabs, 'metadata', tab => ({ ...tab, imageUrl })),
    } : current);
  }

  return <View style={styles.root}>
    <Button label={target ? 'Tracking dialog open' : 'Edit tracking'} palette={buttonPalette}
      onPress={() => onOpen?.({ kind: 'item' })} />
    <Text style={[styles.copy, { color: palette.textMuted }]}>
      {result || 'Edit status, dates, score, notes and tabs for the tracked entry.'}
    </Text>
    <TrackDialog
      open={Boolean(target && session)}
      model={session?.model}
      values={session?.values}
      errors={session?.errors}
      status={session?.status}
      serverError={session?.serverError}
      busy={session?.busy}
      labels={trackLabels}
      palette={formPalette}
      tabs={session?.tabs}
      onChange={updateValue}
      onSubmit={submit}
      onDelete={remove}
      onClose={() => close()}
      onRetry={() => setSession(current => current ? { ...current, status: 'ready', serverError: '' } : current)}
      onRetryTabs={retryTabs}
      onTagToggle={toggleTag}
      onTagCreate={addTag}
      onArtworkSave={saveArtwork}
      onSaveAsNew={saveAsNew}
      onRewatch={toggleRewatch} />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  copy: { fontSize: 12, lineHeight: 18 },
});
