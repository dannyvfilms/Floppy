import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
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
import { emitMediaCardChange, subscribeMediaCardChange } from './mediaCardEvents';
import {
  createTag,
  deleteTrack,
  hasMediaCardTransport,
  loadLists,
  loadTrack,
  loadTrackTabs,
  mediaCardVariant,
  reorderListItem,
  reorderListItems,
  runDiscoverAction,
  saveArtwork,
  saveScore,
  saveTrack,
  setDiscoverHidden,
  setTags,
  toggleList,
} from './mediaCardTransport';

export const surface = {
  id: 'MEDIA-CARD',
  title: 'Media card',
  where: 'Home rails, Discover, Library, Search and List results',
  status: 'ported',
  note: 'Poster, square, landscape and row cards render the shared model with the shared ArtworkImage loading, fallback, provenance and stale states, chips, progress, rating, action overlay, touch/hover reveal, explicit read-only mode and selectable states. The native action host owns the Track and Lists form bodies, the Track song/episode variants, link routing, Discover plan/hide, list reorder and a shared card-change event through the platform transport. Drag reorder exposes an adjustable position and hint, step and accessibility actions, and announces moves and failures; the web Track General form is shared presentation through mountTrackForm. The Expo export compiles the finished card; iOS, Android, browser and screen-reader runtime interaction remain unverified.',
};

const labels = {
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
};

function actionsFor(title, media, trackTitle = 'Edit tracking') {
  return {
    href: '/demo/library',
    items: [
      {
        kind: 'modal',
        modal: 'track',
        tone: 'indigo',
        title: trackTitle,
        glyph: '✎',
        url: '/demo/track',
        vals: { return_url: '/demo/library' },
        target: '#track-demo',
        media,
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
        media,
      },
      {
        kind: 'link',
        tone: 'amber',
        title: 'View your activity history',
        glyph: '◷',
        href: '/demo/history',
        media,
      },
    ],
    ordering: null,
    modals: { track: 'track-demo', lists: 'lists-demo' },
    csrfToken: '',
    clickable: true,
    title,
    media,
  };
}

function discoverActionsFor(title, media) {
  const vals = {
    candidate_media_type: media.mediaType,
    identity_media_type: media.mediaType === 'episode' ? 'episode' : '',
    library_media_type: '',
    source: media.source,
    media_id: media.mediaId,
    season_number: media.seasonNumber != null ? String(media.seasonNumber) : '',
    active_media_type: 'all',
    show_more: '0',
    row_key: 'demo',
    discover_debug: '0',
    title,
    image: '',
    release_date: '',
  };
  return {
    href: '/demo/discover',
    items: [
      {
        kind: 'post',
        tone: 'emerald',
        title: 'Add to Planning',
        glyph: '＋',
        vals: { ...vals, action: 'planning' },
        media,
      },
      {
        kind: 'post',
        tone: 'rose',
        title: 'Hide from Discover',
        glyph: '⦸',
        vals: { ...vals, action: 'dismiss' },
        media,
      },
      {
        kind: 'modal',
        modal: 'lists',
        tone: 'amber',
        title: 'Add to custom lists',
        glyph: '☰',
        url: '/demo/lists',
        vals: { return_url: '/demo/discover' },
        target: '#lists-discover',
        media,
      },
    ],
    ordering: null,
    modals: { lists: 'lists-discover' },
    csrfToken: '',
    clickable: true,
    title,
    media,
  };
}

function identityKey(identity) {
  if (!identity) return '';
  return [
    identity.mediaType,
    identity.source,
    identity.mediaId,
    identity.seasonNumber || '',
    identity.episodeNumber || '',
  ].join('|');
}

const demoMedia = {
  orbit: {
    mediaType: 'tv',
    source: 'tmdb',
    mediaId: '76479',
    title: 'The Quiet Orbit',
    subtitle: 'S1 E6 · The Long Night',
  },
  signal: {
    mediaType: 'podcast',
    source: 'pocketcasts',
    mediaId: 'signal-carrier-wave',
    episodeNumber: 3,
    showId: '77',
    trackId: '301',
    title: 'Signal & Static',
    subtitle: 'Episode 3 · Carrier Wave',
  },
  episode: {
    mediaType: 'episode',
    source: 'tmdb',
    mediaId: '76479',
    seasonNumber: 1,
    episodeNumber: 6,
    title: 'The Long Night',
    subtitle: 'S1 E6 · The Quiet Orbit',
  },
  studio: {
    mediaType: 'movie',
    source: 'tmdb',
    mediaId: '603',
    title: 'Building a Home Studio',
    subtitle: '2024 · 12:40',
  },
  lanterns: {
    mediaType: 'book',
    source: 'openlibrary',
    mediaId: 'OL27448W',
    title: 'Paper Lanterns',
    subtitle: '2022 · 320 pages',
  },
};

const reorderOrdering = {
  listId: '9',
  itemId: '4',
  itemIds: {
    'quiet-orbit': '1',
    'signal-static': '2',
    'paper-lanterns': '3',
    'home-studio': '4',
    'the-long-night': '5',
  },
  url: '/demo/lists/9/reorder',
  labels: {
    first: 'Move to first',
    back: 'Move back',
    next: 'Move next',
    last: 'Move to last',
    drag: 'Drag to reorder',
  },
};

const demoItems = [
  {
    key: 'quiet-orbit',
    model: {
      mediaType: 'tv',
      identity: demoMedia.orbit,
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
      actions: actionsFor('The Quiet Orbit', demoMedia.orbit),
    },
  },
  {
    key: 'signal-static',
    model: {
      mediaType: 'podcast',
      identity: demoMedia.signal,
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
      actions: actionsFor('Signal & Static', demoMedia.signal, 'Add play'),
    },
  },
  {
    key: 'home-studio',
    model: {
      mediaType: 'video',
      identity: demoMedia.studio,
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
      actions: { ...actionsFor('Building a Home Studio', demoMedia.studio), ordering: reorderOrdering },
    },
  },
  {
    key: 'paper-lanterns',
    model: {
      mediaType: 'book',
      identity: demoMedia.lanterns,
      shape: 'poster',
      video: false,
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
      actions: discoverActionsFor('Paper Lanterns', demoMedia.lanterns),
    },
  },
  {
    key: 'the-long-night',
    model: {
      mediaType: 'episode',
      identity: demoMedia.episode,
      shape: 'poster',
      video: false,
      href: '/demo/the-quiet-orbit/s1/e6',
      image: { src: 'https://picsum.photos/seed/floppy-orbit-night/400/600', fallback: '', source: 'primary' },
      title: 'The Long Night',
      altTitle: null,
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [{ kind: 'queue', text: 'S1 E6' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: 'The Quiet Orbit' }, { text: '• 48 min', muted: true }] }],
      rating: null,
      ratingEditable: false,
      actions: actionsFor('The Long Night', demoMedia.episode, 'Mark watched'),
    },
  },
];

const discoverCandidateKeys = new Set(
  demoItems
    .filter(item => item.model.actions?.items?.some(action => action.vals?.action === 'dismiss'))
    .map(item => identityKey(item.model.identity)),
);

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

const demoEpisodeTrack = {
  title: 'The Long Night',
  titleSubtitle: 'S1 E6 · The Quiet Orbit',
  mediaType: 'episode',
  variant: 'episode',
  action: '/demo/episode/watch',
  deleteAction: '/demo/episode/drop',
  csrfToken: 'demo',
  submitLabel: 'Add watch',
  deleteLabel: 'Drop',
  fields: [{ name: 'end_date', label: 'Watch date', type: 'date', value: '2026-10-12' }],
  labels: trackLabels,
  trackTime: false,
};

const demoSongTrack = {
  title: 'Signal & Static',
  titleSubtitle: 'Episode 3 · Carrier Wave',
  mediaType: 'podcast',
  variant: 'song',
  action: '/demo/podcast/play',
  deleteAction: '',
  csrfToken: 'demo',
  submitLabel: 'Add play',
  deleteLabel: 'Delete',
  fields: [{ name: 'end_date', label: 'Play date', type: 'date', value: '2026-10-12' }],
  labels: trackLabels,
  trackTime: false,
};

function demoTrackFor(identity) {
  const variant = mediaCardVariant(identity);
  if (variant === 'episode') return demoEpisodeTrack;
  if (variant === 'song') return demoSongTrack;
  return demoTrack;
}

const demoTrackTabs = [
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
      { label: 'Media type', value: 'tv' },
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
      { id: 'play-1', title: 'In progress', detail: 'Episode 6 · The Long Night', date: '2026-10-12' },
      { id: 'play-2', title: 'Completed', detail: 'Episode 5 · Drift', date: '2026-10-08' },
    ],
  },
  {
    id: 'status-history',
    label: 'Status history',
    kind: 'status-history',
    status: 'ready',
    error: '',
    changes: [
      { id: 'change-1', old: 'Planning', next: 'In progress', reason: 'Manual', date: '2026-10-01' },
      { id: 'change-2', old: '', next: 'Planning', reason: 'Discover', date: '2026-09-28' },
    ],
  },
  {
    id: 'discover',
    label: 'Discover',
    kind: 'discover',
    status: 'ready',
    error: '',
    hidden: false,
    canToggle: true,
    itemId: 'demo-orbit',
  },
];

function updateTab(tabs, id, updater) {
  return tabs.map(tab => (tab.id === id ? updater(tab) : tab));
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function ListsAction({ action, onClose }) {
  const transportReady = hasMediaCardTransport();
  const identity = action.media || { mediaType: 'tv', source: 'tmdb', mediaId: 'demo', title: action.title };
  const fallback = normalizeListsModel(demoLists);
  const [model, setModel] = useState(transportReady ? null : fallback);
  const [status, setStatus] = useState(transportReady ? 'loading' : 'ready');
  const [membership, setMembership] = useState(() => listsMembership(fallback));
  const [tag, setTag] = useState('');
  const [pending, setPending] = useState({});
  const [errors, setErrors] = useState({});
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!transportReady) return undefined;
    let alive = true;
    setStatus('loading');
    setErrors({});
    loadLists(identity, action.title)
      .then(data => {
        if (!alive) return;
        const next = normalizeListsModel(data);
        setModel(next);
        setMembership(listsMembership(next));
        setStatus('ready');
      })
      .catch(() => { if (alive) setStatus('error'); });
    return () => { alive = false; };
  }, [attempt, transportReady, identity.mediaType, identity.source, identity.mediaId, action.title]);

  async function toggle(list) {
    if (pending[list.id]) return;
    setPending(current => ({ ...current, [list.id]: true }));
    setErrors(current => ({ ...current, [list.id]: '' }));
    try {
      const has = Boolean(membership[list.id]);
      if (transportReady) {
        const data = await toggleList(identity, list.id, has);
        setMembership(current => applyListToggle(current, list.id, data.hasItem));
      } else {
        await delay(250);
        setMembership(current => applyListToggle(current, list.id, !has));
      }
    } catch (error) {
      setErrors(current => ({ ...current, [list.id]: error.message || listLabels.toggleFailed }));
    } finally {
      setPending(current => ({ ...current, [list.id]: false }));
    }
  }

  return <ListsForm
    model={model}
    membership={membership}
    tag={tag}
    status={status}
    pending={pending}
    errors={errors}
    labels={listLabels}
    palette={formPalette}
    showHeader={false}
    onTagChange={setTag}
    onRetry={() => setAttempt(current => current + 1)}
    onClose={onClose}
    onToggle={toggle} />;
}

function TrackAction({ action, onClose }) {
  const transportReady = hasMediaCardTransport();
  const identity = action.media || { mediaType: 'tv', source: 'tmdb', mediaId: 'demo', title: action.title };
  const variant = mediaCardVariant(identity);
  const fallback = normalizeTrackForm(demoTrackFor(identity));
  const [model, setModel] = useState(transportReady ? null : fallback);
  const [values, setValues] = useState(() => (transportReady ? {} : initialTrackValues(fallback)));
  const [tabs, setTabs] = useState(transportReady || variant ? [] : demoTrackTabs);
  const [tracked, setTracked] = useState(false);
  const [status, setStatus] = useState(transportReady ? 'loading' : 'ready');
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState('');
  const [errors, setErrors] = useState({});
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!transportReady) return undefined;
    let alive = true;
    setStatus('loading');
    setServerError('');
    loadTrack(identity)
      .then(data => {
        if (!alive) return;
        const next = normalizeTrackForm(data.model);
        setModel(next);
        setValues(initialTrackValues(next));
        setTabs(data.tabs || []);
        setTracked(Boolean(data.tracked));
        setStatus('ready');
      })
      .catch(error => {
        if (!alive) return;
        setServerError(error.message || '');
        setStatus('error');
      });
    return () => { alive = false; };
  }, [attempt, transportReady, identity.mediaType, identity.source, identity.mediaId,
    identity.seasonNumber, identity.episodeNumber, identity.albumId, identity.trackId]);

  function change(name, value) {
    setValues(current => ({ ...current, [name]: value }));
    setErrors(current => ({ ...current, [name]: '' }));
  }

  async function submit() {
    setBusy(true);
    setServerError('');
    try {
      if (transportReady) {
        await saveTrack(identity, model, values, tracked);
        const refreshed = await loadTrack(identity);
        setTracked(Boolean(refreshed.tracked));
        setTabs(refreshed.tabs || []);
      } else {
        await delay(500);
      }
      emitMediaCardChange({
        identity,
        source: 'track',
        tracked: true,
        ...(values.status !== undefined ? { status: values.status } : {}),
        ...(values.score !== undefined ? { score: values.score === '' ? null : Number(values.score) } : {}),
      });
      onClose?.();
    } catch (error) {
      setServerError(error.message || '');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setServerError('');
    try {
      if (transportReady) await deleteTrack(identity, model);
      else await delay(400);
      emitMediaCardChange({ identity, source: 'track', tracked: false, status: null });
      onClose?.();
    } catch (error) {
      setServerError(error.message || '');
    } finally {
      setBusy(false);
    }
  }

  async function retryTabs() {
    if (!transportReady) return;
    setTabs(current => current.map(tab => ({ ...tab, status: 'loading', error: '' })));
    setTabs(await loadTrackTabs(identity));
  }

  async function toggleTag(tag) {
    const tagTab = tabs.find(tab => tab.id === 'tags');
    const applied = (tagTab?.tags || []).filter(entry => entry.hasTag).map(entry => entry.id);
    const ids = tag.hasTag ? applied.filter(id => id !== tag.id) : [...applied, tag.id];
    setTabs(current => updateTab(current, 'tags', tab => ({
      ...tab,
      tags: tab.tags.map(entry => (entry.id === tag.id ? { ...entry, pending: true, error: '' } : entry)),
    })));
    try {
      if (transportReady) await setTags(identity, ids);
      else await delay(200);
      setTabs(current => updateTab(current, 'tags', tab => ({
        ...tab,
        tags: tab.tags.map(entry => (entry.id === tag.id ? { ...entry, hasTag: !tag.hasTag, pending: false } : entry)),
      })));
    } catch (error) {
      setTabs(current => updateTab(current, 'tags', tab => ({
        ...tab,
        tags: tab.tags.map(entry => (entry.id === tag.id ? { ...entry, pending: false, error: error.message } : entry)),
      })));
    }
  }

  async function addTag(name) {
    const created = transportReady ? await createTag(name) : { id: `demo-${Date.now()}`, name };
    const tagTab = tabs.find(tab => tab.id === 'tags');
    const applied = (tagTab?.tags || []).filter(entry => entry.hasTag).map(entry => entry.id);
    if (transportReady) await setTags(identity, [...applied, created.id]);
    setTabs(current => updateTab(current, 'tags', tab => ({
      ...tab,
      tags: [...(tab.tags || []), { id: created.id, name: created.name, hasTag: true, pending: false, error: '' }],
    })));
  }

  async function saveArtworkUrl(imageUrl) {
    if (!imageUrl) return;
    if (transportReady) await saveArtwork(identity, imageUrl);
    else await delay(200);
    setTabs(current => updateTab(current, 'metadata', tab => ({ ...tab, imageUrl })));
  }

  async function toggleDiscover(hidden, itemId) {
    if (transportReady) await setDiscoverHidden(itemId, hidden);
    else await delay(200);
    setTabs(current => updateTab(current, 'discover', tab => ({ ...tab, hidden })));
    emitMediaCardChange({
      identity,
      source: 'discover',
      action: hidden ? 'hide' : 'unhide',
      hidden,
    });
  }

  return <TrackForm
    model={model}
    values={values}
    errors={errors}
    status={status}
    serverError={serverError}
    busy={busy}
    labels={trackLabels}
    palette={formPalette}
    showHeader={false}
    tabs={tabs}
    onChange={change}
    onRetry={() => setAttempt(current => current + 1)}
    onRetryTabs={retryTabs}
    onDelete={remove}
    onClose={onClose}
    onSubmit={submit}
    onTagToggle={toggleTag}
    onTagCreate={addTag}
    onArtworkSave={saveArtworkUrl}
    onDiscoverToggle={toggleDiscover} />;
}

function DiscoverAction({ action, onClose }) {
  const transportReady = hasMediaCardTransport();
  const vals = action?.vals || {};
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState('');
  const planning = vals.action === 'planning';

  useEffect(() => {
    let alive = true;
    setFailed('');
    (transportReady ? runDiscoverAction(vals) : delay(350))
      .then(() => {
        if (!alive) return;
        emitMediaCardChange({
          identity: {
            mediaType: vals.candidate_media_type,
            source: vals.source,
            mediaId: vals.media_id,
          },
          source: 'discover',
          action: planning ? 'planning' : 'dismiss',
          ...(planning ? { status: 'Planning', tracked: true } : { hidden: true, tracked: false }),
        });
        onClose?.();
      })
      .catch(error => { if (alive) setFailed(error.message || ''); });
    return () => { alive = false; };
  }, [attempt, transportReady, planning, action]);

  if (failed) {
    return <View style={styles.hostStack}>
      <Text accessibilityRole="alert" style={styles.hostError}>{failed}</Text>
      <Button label="Try again" tone="surface" palette={formPalette}
        onPress={() => setAttempt(current => current + 1)} />
    </View>;
  }
  return <Text accessibilityRole="status" accessibilityLiveRegion="polite" style={styles.hostBody}>
    {planning ? `Adding “${vals.title || action.title}” to Planning…` : `Hiding “${vals.title || action.title}” from Discover…`}
  </Text>;
}

function ActionBody({ action, onClose }) {
  if (!action) return null;
  if (action.modal === 'lists') return <ListsAction action={action} onClose={onClose} />;
  if (action.modal === 'track') return <TrackAction action={action} onClose={onClose} />;
  if (action.kind === 'post') return <DiscoverAction action={action} onClose={onClose} />;
  return null;
}

function nearestCardIndex(order, layouts, key, dx, dy, fallback) {
  const start = layouts[key];
  if (!start) return fallback;
  const x = start.x + start.width / 2 + dx;
  const y = start.y + start.height / 2 + dy;
  let best = fallback;
  let bestDistance = Infinity;
  order.forEach((candidate, index) => {
    const layout = layouts[candidate];
    if (!layout) return;
    const distance = (layout.x + layout.width / 2 - x) ** 2
      + (layout.y + layout.height / 2 - y) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return best;
}

async function persistListOrder(ordering, orderedKeys, targetIndex, fromIndex) {
  const itemIds = orderedKeys.map(key => ordering.itemIds?.[key]);
  if (ordering.itemIds && itemIds.every(Boolean)) {
    await reorderListItems(ordering, itemIds);
    return;
  }
  if (targetIndex === 0) {
    await reorderListItem(ordering, 'first');
    return;
  }
  if (targetIndex === orderedKeys.length - 1) {
    await reorderListItem(ordering, 'last');
    return;
  }
  const step = targetIndex < fromIndex ? 'back' : 'next';
  for (let index = 0; index < Math.abs(targetIndex - fromIndex); index += 1) {
    await reorderListItem(ordering, step);
  }
}

function moveByStep(order, key, step) {
  const index = order.indexOf(key);
  if (index < 0) return order;
  const target = step === 'first' ? 0
    : step === 'last' ? order.length - 1
      : step === 'back' ? Math.max(0, index - 1)
        : step === 'next' ? Math.min(order.length - 1, index + 1) : index;
  if (target === index) return order;
  const next = [...order];
  next.splice(index, 1);
  next.splice(target, 0, key);
  return next;
}

function applyMediaCardChange(model, change) {
  if (!change) return model;
  const next = { ...model };
  if (Object.prototype.hasOwnProperty.call(change, 'status')) {
    next.statusChip = change.status
      ? { kind: 'status', status: change.status, hideOnMobile: false }
      : { kind: 'no-status', hideOnMobile: false };
  }
  if (Object.prototype.hasOwnProperty.call(change, 'score') && next.rating) {
    next.rating = {
      ...next.rating,
      value: change.score,
      label: change.score == null ? null : String(change.score),
    };
  }
  return next;
}

export default function MediaCardSlot({
  onOpenDetail,
  onOpenLink,
  readOnly = false,
  selectionMode = false,
  selectedKeys = [],
  onToggleSelection,
}) {
  const { width } = useWindowDimensions();
  const [ratings, setRatings] = useState({});
  const [pendingAction, setPendingAction] = useState(null);
  const [order, setOrder] = useState(() => demoItems.map(item => item.key));
  const [changes, setChanges] = useState({});
  const [drag, setDrag] = useState(null);
  const [actionError, setActionError] = useState('');
  const layouts = useRef({});
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

  useEffect(() => subscribeMediaCardChange(change => {
    const keys = [];
    if (change.identity) keys.push(identityKey(change.identity));
    if (Array.isArray(change.identities)) keys.push(...change.identities.map(identityKey));
    if (!keys.length) return;
    if (change.source === 'discover'
      && ['planning', 'dismiss', 'hide'].includes(change.action)) {
      const removed = demoItems
        .filter(item => discoverCandidateKeys.has(identityKey(item.model.identity))
          && keys.includes(identityKey(item.model.identity)))
        .map(item => item.key);
      if (removed.length) {
        setOrder(current => current.filter(key => !removed.includes(key)));
      }
    }
    setChanges(current => {
      const next = { ...current };
      keys.forEach(key => { next[key] = { ...(next[key] || {}), ...change }; });
      return next;
    });
  }), []);

  async function rate(item, score) {
    setRatings(current => ({ ...current, [item.key]: score }));
    emitMediaCardChange({ identity: item.model.identity, source: 'rating', score });
    if (!hasMediaCardTransport()) return;
    try {
      await saveScore(item.model.identity, score);
    } catch (error) {
      setRatings(current => {
        const next = { ...current };
        delete next[item.key];
        return next;
      });
      setActionError(error.message || 'Could not save this rating.');
      AccessibilityInfo.announceForAccessibility?.(error.message || 'Could not save this rating.');
    }
  }

  function announce(message) {
    AccessibilityInfo.announceForAccessibility?.(message);
  }

  function runAction(action) {
    if (!action) return;
    if (action.kind === 'link') {
      setPendingAction(null);
      (onOpenLink || onOpenDetail)?.(action.href);
      return;
    }
    setPendingAction(action);
  }

  async function reorder(item, step) {
    const next = moveByStep(order, item.key, step);
    if (next === order) return;
    const previous = order;
    setOrder(next);
    setActionError('');
    const ordering = item.model.actions?.ordering;
    if (!hasMediaCardTransport() || !ordering) return;
    try {
      await reorderListItem(ordering, step);
      announce(`${item.model.title} moved ${step}.`);
    } catch (error) {
      setOrder(previous);
      setActionError(error.message || 'Could not reorder this item.');
      announce(error.message || 'Could not reorder this item.');
    }
  }

  async function moveTo(item, targetIndex) {
    const fromIndex = order.indexOf(item.key);
    if (fromIndex < 0 || targetIndex < 0 || targetIndex >= order.length
      || targetIndex === fromIndex) return;
    const next = [...order];
    next.splice(fromIndex, 1);
    next.splice(targetIndex, 0, item.key);
    const previous = order;
    setOrder(next);
    setActionError('');
    const ordering = item.model.actions?.ordering;
    if (!hasMediaCardTransport() || !ordering) return;
    try {
      await persistListOrder(ordering, next, targetIndex, fromIndex);
      announce(`${item.model.title} moved to position ${targetIndex + 1} of ${order.length}.`);
    } catch (error) {
      setOrder(previous);
      setActionError(error.message || 'Could not reorder this item.');
      announce(error.message || 'Could not reorder this item.');
    }
  }

  function handleReorderDrag(item, event) {
    if (!item.model.actions?.ordering) return;
    const index = order.indexOf(item.key);
    if (event.phase === 'start') {
      setDrag({ key: item.key, fromIndex: index, dx: 0, dy: 0, targetIndex: index });
      setActionError('');
      return;
    }
    if (event.phase === 'cancel') {
      setDrag(null);
      return;
    }
    const targetIndex = nearestCardIndex(order, layouts.current, item.key,
      event.dx, event.dy, index);
    setDrag(current => (current && current.key === item.key
      ? { ...current, dx: event.dx, dy: event.dy, targetIndex }
      : current));
    if (event.phase === 'end') {
      setDrag(null);
      moveTo(item, targetIndex);
    }
  }

  const items = order.map(key => demoItems.find(item => item.key === key)).filter(Boolean);

  return <>
    <View style={styles.grid}>
      {items.map((item, index) => {
        const value = ratings[item.key];
        let model = item.model;
        if (value !== undefined) {
          model = {
            ...model,
            rating: model.rating && {
              ...model.rating,
              value,
              label: value == null ? null : String(value),
            },
          };
        }
        model = applyMediaCardChange(model, changes[identityKey(item.model.identity)]);
        if (model.actions?.ordering) {
          model = {
            ...model,
            actions: {
              ...model.actions,
              ordering: {
                ...model.actions.ordering,
                position: index + 1,
                count: items.length,
              },
            },
          };
        }
        const selection = selectionMode ? {
          active: true,
          selected: selectedKeys.includes(item.key),
          label: `Select ${model.title}`,
          toggle: () => onToggleSelection?.(item.key),
        } : undefined;
        const isDragging = drag?.key === item.key;
        return <View key={item.key}
          onLayout={event => { layouts.current[item.key] = event.nativeEvent.layout; }}
          style={[
            isDragging && styles.draggingCard,
            !isDragging && drag && drag.targetIndex === index && styles.dropTarget,
          ]}>
          <MediaCardView model={model} labels={labels} palette={mediaCardPalette}
            width={cardWidth} onOpen={onOpenDetail}
            onOpenLink={onOpenLink || onOpenDetail}
            onAction={runAction}
            readOnly={readOnly}
            selection={selection}
            onReorder={step => reorder(item, step)}
            onReorderDrag={event => handleReorderDrag(item, event)}
            dragging={isDragging}
            renderActionIcon={renderActionIcon}
            onRate={score => rate(item, score)}
            renderRating={({ value: score, label, scaleMax, palette, onSelect }) => <RatingStars
              scaleMax={scaleMax} value={score} label={label} onSelect={onSelect} palette={palette}
              renderStar={lit => <Text style={[styles.pickerStar, { color: lit ? palette.lit : palette.unlit }]}>★</Text>} />} />
        </View>;
      })}
    </View>
    {actionError ? <Text role="status" accessibilityRole="alert" accessibilityLiveRegion="polite"
      style={styles.actionError}>{actionError}</Text> : null}
    <MediaCardActionHost action={pendingAction} open={!!pendingAction} labels={labels}
      palette={mediaCardPalette} onClose={() => setPendingAction(null)}>
      <ActionBody key={pendingAction?.target || pendingAction?.title || 'closed'} action={pendingAction}
        onClose={() => setPendingAction(null)} />
    </MediaCardActionHost>
  </>;
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  draggingCard: { zIndex: 20, elevation: 8, opacity: 0.9 },
  dropTarget: { opacity: 0.72 },
  pickerStar: { fontSize: 20 },
  actionGlyph: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  hostBody: { color: '#a1a1aa', fontSize: 13, lineHeight: 19 },
  hostStack: { gap: spacing.sm },
  hostError: { color: '#f87171', fontSize: 12, lineHeight: 17 },
  actionError: { color: '#f87171', fontSize: 12, lineHeight: 17 },
});
