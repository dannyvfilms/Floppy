import React, { useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { ListsForm } from '../../../frontend/ui/ListsFormView';
import { MediaCardActionHost } from '../../../frontend/ui/MediaCardActionHost';
import { MediaCardView } from '../../../frontend/ui/MediaCardView';
import { TrackForm } from '../../../frontend/ui/TrackForm';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import {
  applyListToggle,
  initialTrackValues,
  listsMembership,
  normalizeListsModel,
  normalizeTrackForm,
} from '../../../frontend/ui/mediaCardForms';
import { mediaCardPalette, spacing } from '../theme';

export const surface = {
  id: 'MEDIA-CARD',
  title: 'Media card',
  where: 'Home rails, Discover, Library, Search and List results',
  status: 'in_progress',
  note: 'Poster, square, landscape and row cards render the shared model with artwork fallback, chips, progress, rating, action overlay, touch/hover reveal and read-only/selectable states. The native action host now owns the Track and Lists form bodies; this port is connecting those forms to the platform JSON transport and CSRF boundary, then adding the remaining Track tabs. Discover writes, list reorder, bulk selection and runtime evidence remain outstanding.',
};

const labels = {
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
};

function actionsFor(title) {
  return {
    href: '/demo/library',
    items: [
      {
        kind: 'modal',
        modal: 'track',
        tone: 'indigo',
        title: 'Edit tracking',
        glyph: '✎',
        url: '/demo/track',
        vals: { return_url: '/demo/library' },
        target: '#track-demo',
      },
      {
        kind: 'modal',
        modal: 'lists',
        tone: 'emerald',
        title: 'Add to custom lists',
        glyph: '☰',
        url: '/demo/lists',
        vals: { return_url: '/demo/library' },
        target: '#lists-demo',
      },
      {
        kind: 'link',
        tone: 'amber',
        title: 'View your activity history',
        glyph: '◷',
        href: '/demo/history',
      },
    ],
    ordering: null,
    modals: { track: 'track-demo', lists: 'lists-demo' },
    csrfToken: '',
    clickable: true,
    title,
  };
}

const demoItems = [
  {
    key: 'quiet-orbit',
    model: {
      mediaType: 'tv',
      shape: 'poster',
      video: false,
      href: '/demo/the-quiet-orbit',
      image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
      title: 'The Quiet Orbit',
      altTitle: null,
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [{ kind: 'next-episode', text: 'Next ep', href: '/demo/the-quiet-orbit/next' }],
      titleLinks: [],
      progressBar: { percent: 62, paused: false },
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• 6 / 10 episodes', muted: true }] }],
      rating: { label: '8.0', value: 8, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: true,
      actions: actionsFor('The Quiet Orbit'),
    },
  },
  {
    key: 'signal-static',
    model: {
      mediaType: 'podcast',
      shape: 'square',
      video: false,
      href: '/demo/signal-and-static',
      image: { src: 'https://picsum.photos/seed/floppy-signal/400/400', fallback: '', source: 'primary' },
      title: 'Signal & Static',
      altTitle: 'Signal and Static',
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [],
      titleLinks: [],
      progressBar: { percent: 38, paused: true },
      lines: [{ join: 'plain', parts: [{ text: '2023' }, { text: '• 3 / 8 episodes', muted: true }] }],
      rating: { label: '4.5', value: 4.5, scaleMax: 5, rateLabel: 'Rate' },
      ratingEditable: true,
      actions: actionsFor('Signal & Static'),
    },
  },
  {
    key: 'home-studio',
    model: {
      mediaType: 'video',
      shape: 'landscape',
      video: true,
      href: '/demo/building-a-home-studio',
      image: { src: 'https://picsum.photos/seed/floppy-studio/800/450', fallback: '', source: 'primary' },
      title: 'Building a Home Studio',
      altTitle: null,
      statusChip: { kind: 'status', status: 'Completed', hideOnMobile: false },
      cornerChips: [{ kind: 'runtime', text: '12:40' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• Watched', muted: true }] }],
      rating: null,
      ratingEditable: true,
      actions: actionsFor('Building a Home Studio'),
    },
  },
  {
    key: 'paper-lanterns',
    model: {
      mediaType: 'book',
      shape: 'poster',
      video: false,
      publicView: true,
      href: '/demo/paper-lanterns',
      image: { src: null, fallback: '', source: 'primary' },
      title: 'Paper Lanterns',
      altTitle: null,
      statusChip: {
        kind: 'media-type',
        type: 'book',
        style: 'soft',
        color: '#D946EF',
        contrast: '#FFFFFF',
        label: 'Book',
      },
      cornerChips: [{ kind: 'collected', text: '4/8 collected', title: '4 of 8 episodes collected' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2022' }, { text: '• 0 / 320 pages', muted: true }] }],
      rating: { label: '6.5', value: 6.5, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: false,
      actions: null,
    },
  },
];

function actionGlyph(action) {
  if (action.kind === 'drag') return '≡';
  if (action.modal === 'track') return '✎';
  if (action.modal === 'lists') return '☰';
  if (action.vals?.action === 'planning') return '＋';
  if (action.vals?.action === 'dismiss') return '⦸';
  if (action.kind === 'link') return '◷';
  return '•';
}

function renderActionIcon(action) {
  return <Text accessible={false} style={styles.actionGlyph}>{actionGlyph(action)}</Text>;
}

const listLabels = {
  title: 'Lists',
  close: 'Close',
  loading: 'Loading',
  loadFailed: "Couldn't load your lists.",
  retry: 'Try again',
  filterByTag: 'Filter by tag',
  allLists: 'All lists',
  countOne: 'On %s list',
  countMany: 'On %s lists',
  add: 'Add',
  remove: 'Remove',
  addTo: 'Add item to %s',
  removeFrom: 'Remove item from %s',
  emptyTag: 'No lists with this tag.',
  emptyLists: "You haven't created any lists yet.",
  toggleFailed: "Couldn't update this list. Please try again.",
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
  dateTime: {},
};

const formPalette = {
  ...mediaCardPalette,
  textSecondary: mediaCardPalette.textSecondary,
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
  dateTime: mediaCardPalette,
};

const demoLists = {
  itemId: 1,
  title: 'The Quiet Orbit',
  lists: [
    { id: '1', name: 'Weekend queue', hasItem: true, tags: ['Sci-fi'] },
    { id: '2', name: 'Comfort watches', hasItem: false, tags: ['Comfort'] },
    { id: '3', name: 'With friends', hasItem: false, tags: [] },
  ],
  tags: ['Comfort', 'Sci-fi'],
  toggleUrl: '/demo/lists/toggle',
  csrfToken: 'demo',
};

const demoTrack = {
  title: 'The Quiet Orbit',
  titleSubtitle: 'S1 E6 · The Long Night',
  mediaType: 'tv',
  action: '/demo/track',
  deleteAction: '/demo/track/delete',
  csrfToken: 'demo',
  submitLabel: 'Save',
  deleteLabel: 'Delete',
  fields: [
    {
      name: 'status',
      label: 'Status',
      type: 'select',
      value: 'In progress',
      required: true,
      options: [
        { value: 'Planning', label: 'Planning' },
        { value: 'In progress', label: 'In progress' },
        { value: 'Paused', label: 'Paused' },
        { value: 'Completed', label: 'Completed' },
        { value: 'Dropped', label: 'Dropped' },
      ],
    },
    { name: 'score', label: 'Score', type: 'number', value: '8', min: 0, max: 10 },
    { name: 'progress', label: 'Progress', type: 'number', value: '6', min: 0, max: 10, help: 'Episodes watched' },
    { name: 'start_date', label: 'Start date', type: 'date', value: '2026-10-01' },
    { name: 'end_date', label: 'End date', type: 'date', value: '' },
  ],
  notes: { value: 'Watching with the family.', label: 'Notes' },
  labels: trackLabels,
  trackTime: false,
};

function ActionBody({ action, onClose }) {
  const [listsModel] = useState(() => normalizeListsModel(demoLists));
  const [membership, setMembership] = useState(() => listsMembership(listsModel));
  const [tag, setTag] = useState('');
  const [pending, setPending] = useState({});
  const [listErrors, setListErrors] = useState({});
  const [listStatus, setListStatus] = useState('ready');
  const [trackModel] = useState(() => normalizeTrackForm(demoTrack));
  const [trackValues, setTrackValues] = useState(() => initialTrackValues(trackModel));
  const [trackErrors, setTrackErrors] = useState({});
  const [trackStatus, setTrackStatus] = useState('ready');
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackServerError, setTrackServerError] = useState('');

  if (!action) return null;
  if (action.modal === 'lists') {
    return <ListsForm
      model={listsModel}
      membership={membership}
      tag={tag}
      status={listStatus}
      pending={pending}
      errors={listErrors}
      labels={listLabels}
      palette={formPalette}
      showHeader={false}
      onTagChange={setTag}
      onRetry={() => setListStatus('ready')}
      onClose={onClose}
      onToggle={list => {
        if (pending[list.id]) return;
        setPending(current => ({ ...current, [list.id]: true }));
        setListErrors(current => ({ ...current, [list.id]: '' }));
        setTimeout(() => {
          setMembership(current => applyListToggle(current, list.id, !current[list.id]));
          setPending(current => ({ ...current, [list.id]: false }));
        }, 350);
      }} />;
  }
  if (action.modal === 'track') {
    return <TrackForm
      model={trackModel}
      values={trackValues}
      errors={trackErrors}
      status={trackStatus}
      serverError={trackServerError}
      busy={trackBusy}
      labels={trackLabels}
      palette={formPalette}
      showHeader={false}
      onChange={(name, value) => {
        setTrackValues(current => ({ ...current, [name]: value }));
        setTrackErrors(current => ({ ...current, [name]: '' }));
      }}
      onRetry={() => {
        setTrackStatus('ready');
        setTrackServerError('');
      }}
      onDelete={() => setTrackServerError('Delete is not available in this demo.')}
      onClose={onClose}
      onSubmit={() => {
        setTrackBusy(true);
        setTrackServerError('');
        setTimeout(() => {
          setTrackBusy(false);
          onClose?.();
        }, 600);
      }} />;
  }
  if (action.kind === 'post') {
    return <Text style={styles.hostBody}>Discover plan and hide use the existing server POST contract. The native write adapter is not ported yet.</Text>;
  }
  return <Text style={styles.hostBody}>This link is routed by the platform navigation adapter.</Text>;
}

export default function MediaCardSlot({ onOpenDetail }) {
  const { width } = useWindowDimensions();
  const [ratings, setRatings] = useState({});
  const [pendingAction, setPendingAction] = useState(null);
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

  return <>
    <View style={styles.grid}>
      {demoItems.map(item => {
        const value = ratings[item.key];
        const model = value === undefined ? item.model : {
          ...item.model,
          rating: item.model.rating && {
            ...item.model.rating,
            value,
            label: value == null ? null : String(value),
          },
        };
        return <MediaCardView key={item.key} model={model} labels={labels} palette={mediaCardPalette}
          width={cardWidth} onOpen={onOpenDetail}
          onOpenLink={onOpenDetail}
          onAction={setPendingAction}
          renderActionIcon={renderActionIcon}
          onRate={score => setRatings(current => ({ ...current, [item.key]: score }))}
          renderRating={({ value, label, scaleMax, palette, onSelect }) => <RatingStars
            scaleMax={scaleMax} value={value} label={label} onSelect={onSelect} palette={palette}
            renderStar={lit => <Text style={[styles.pickerStar, { color: lit ? palette.lit : palette.unlit }]}>★</Text>} />} />;
      })}
    </View>
    <MediaCardActionHost action={pendingAction} open={!!pendingAction} labels={labels}
      palette={mediaCardPalette} onClose={() => setPendingAction(null)}>
      <ActionBody key={pendingAction?.target || 'closed'} action={pendingAction}
        onClose={() => setPendingAction(null)} />
    </MediaCardActionHost>
  </>;
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  pickerStar: { fontSize: 20 },
  actionGlyph: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  hostBody: { color: '#a1a1aa', fontSize: 13, lineHeight: 19 },
});
