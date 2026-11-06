import React, { useMemo, useState } from 'react';
import { AccessibilityInfo, StyleSheet, Text, View } from 'react-native';
import { MediaTable } from '../../../frontend/ui/MediaTable';
import { MediaColumnMenu } from '../../../frontend/ui/ColumnMenu';
import { MediaCardActionHost } from '../../../frontend/ui/MediaCardActionHost';
import { TrackForm } from '../../../frontend/ui/TrackForm';
import { initialTrackValues, normalizeTrackForm } from '../../../frontend/ui/mediaCardForms';
import { mediaCardPalette, palette, spacing } from '../theme';

export const surface = {
  id: 'TABLES',
  status: 'in_progress',
  title: 'Table view and columns',
  where: 'Library and list table layouts',
  note: 'The shared React Native media table and column menu render configurable columns with real client-side sorting (title, media type, score, progress, status, runtime, time watched, release and added dates, genres), score/status/progress/units cells and accessible horizontal scrolling. The column menu reorders and hides columns while keeping the fixed poster and title columns. Each row exposes Track and Open actions: Track opens the shared tracking form in the shared action host and updates that row status and score in local demo state, and Open follows the row detail route. Column changes and tracking edits stay in local component state until account transport is wired; the browser interaction pass and iOS/Android runtime and accessibility passes remain.',
};

const STATUS_RANK = {
  Planning: 0,
  'In progress': 1,
  Completed: 2,
  Paused: 3,
  Dropped: 4,
};

const STATUS_OPTIONS = [{ value: '', label: 'No Status' }, ...Object.keys(STATUS_RANK).map(value => ({ value, label: value }))];

const COLUMNS = [
  { key: 'image', label: '', width: 56, fixed: true, visible: true },
  { key: 'title', label: 'Title', width: 240, primary: true, fixed: true, visible: true },
  { key: 'media_type', label: 'Media Type', width: 120, align: 'center', visible: true },
  { key: 'score', label: 'Score', width: 100, align: 'center', visible: true },
  { key: 'progress', label: 'Progress', width: 130, align: 'center', visible: true },
  { key: 'status', label: 'Status', width: 120, align: 'center', visible: true },
  { key: 'runtime', label: 'Runtime', width: 110, align: 'center', visible: true },
  { key: 'time_watched', label: 'Time Watched', width: 140, align: 'center', visible: true },
  { key: 'release_date', label: 'Release Date', width: 130, align: 'center', visible: false },
  { key: 'date_added', label: 'Date Added', width: 130, align: 'center', visible: false },
  { key: 'genres', label: 'Genres', width: 200, visible: false },
];

const ACTION_COLUMN = { key: 'actions', label: 'Actions', width: 150, align: 'center', sortable: false };

const ROWS = [
  {
    id: 'dune', title: 'Dune: Part Two',
    sort: {
      score: 8.6, progress: 1, status: STATUS_RANK.Completed, runtime: 166,
      time_watched: 166, release_date: 20240301, date_added: 20250212, genres: 'Sci-Fi',
    },
    track: {
      mediaType: 'movie', progressLabel: 'Times watched', progressValue: '1', progressMax: 1,
      startDate: '2025-02-12', endDate: '2025-02-13',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-dune/80/80', alt: 'Dune: Part Two' },
      title: { kind: 'title', text: 'Dune: Part Two', href: '#open:dune' },
      media_type: { kind: 'text', text: 'Movie', muted: true },
      score: { kind: 'score', rated: true, text: '8.6' },
      progress: { kind: 'text', text: 'Watched' },
      status: { kind: 'status', text: 'Completed' },
      runtime: { kind: 'text', text: '2h 46m' },
      time_watched: { kind: 'text', text: '2h 46m' },
      release_date: { kind: 'text', text: 'Mar 1, 2024' },
      date_added: { kind: 'text', text: 'Feb 12, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Sci-Fi' }, { label: 'Drama' }] },
    },
  },
  {
    id: 'orbit', title: 'The Quiet Orbit',
    sort: {
      score: 8.0, progress: 0.6, status: STATUS_RANK['In progress'], runtime: 48,
      time_watched: 288, release_date: 20240101, date_added: 20250130, genres: 'Mystery',
    },
    track: {
      mediaType: 'tv', progressLabel: 'Episodes watched', progressValue: '6', progressMax: 10,
      startDate: '2025-01-30', endDate: '',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-orbit/80/80', alt: 'The Quiet Orbit' },
      title: { kind: 'title', text: 'The Quiet Orbit', href: '#open:orbit' },
      media_type: { kind: 'text', text: 'Show', muted: true },
      score: { kind: 'score', rated: true, text: '8.0' },
      progress: { kind: 'progress', text: '6', maxText: ' / 10 episodes', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '48m' },
      time_watched: { kind: 'text', text: '4h 48m' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'Jan 30, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Mystery' }] },
    },
  },
  {
    id: 'hades', title: 'Hades II',
    sort: {
      score: 9.1, progress: 0.23, status: STATUS_RANK['In progress'], runtime: null,
      time_watched: 840, release_date: 20240101, date_added: 20250602, genres: 'Roguelike',
    },
    track: {
      mediaType: 'game', progressLabel: 'Hours played', progressValue: '14', progressMax: 60,
      startDate: '2025-06-02', endDate: '',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-hades/80/80', alt: 'Hades II' },
      title: { kind: 'title', text: 'Hades II', href: '#open:hades' },
      media_type: { kind: 'text', text: 'Game', muted: true },
      score: { kind: 'score', rated: true, text: '9.1' },
      progress: { kind: 'progress', text: '14h played', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '—', muted: true },
      time_watched: { kind: 'text', text: '14h' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'Jun 2, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Roguelike' }, { label: 'Action' }] },
    },
  },
  {
    id: 'signal', title: 'Signal & Static',
    sort: {
      score: 4.5, progress: 0.375, status: STATUS_RANK['In progress'], runtime: 52,
      time_watched: 156, release_date: 20230101, date_added: 20250304, genres: 'Fiction',
    },
    track: {
      mediaType: 'podcast', progressLabel: 'Episodes played', progressValue: '3', progressMax: 8,
      startDate: '2025-03-04', endDate: '',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-signal/80/80', alt: 'Signal & Static' },
      title: { kind: 'title', text: 'Signal & Static', href: '#open:signal' },
      media_type: { kind: 'text', text: 'Podcast', muted: true },
      score: { kind: 'score', rated: true, text: '4.5' },
      progress: { kind: 'progress', text: '3', maxText: ' / 8 episodes', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '52m' },
      time_watched: { kind: 'text', text: '2h 36m' },
      release_date: { kind: 'text', text: '2023' },
      date_added: { kind: 'text', text: 'Mar 4, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Fiction' }] },
    },
  },
  {
    id: 'paper', title: 'Paper Lanterns',
    sort: {
      score: 6.5, progress: 0, status: STATUS_RANK.Planning, runtime: null,
      time_watched: null, release_date: 20220101, date_added: 20250418, genres: 'Fantasy',
    },
    track: {
      mediaType: 'book', progressLabel: 'Pages read', progressValue: '0', progressMax: 320,
      startDate: '', endDate: '',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-paper/80/80', alt: 'Paper Lanterns' },
      title: { kind: 'title', text: 'Paper Lanterns', href: '#open:paper' },
      media_type: { kind: 'text', text: 'Book', muted: true },
      score: { kind: 'score', rated: true, text: '6.5' },
      progress: { kind: 'progress', text: '0', maxText: ' / 320 pages' },
      status: { kind: 'status', text: 'Planning' },
      runtime: { kind: 'text', text: '—', muted: true },
      time_watched: { kind: 'text', text: '—', muted: true },
      release_date: { kind: 'text', text: '2022' },
      date_added: { kind: 'text', text: 'Apr 18, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Fantasy' }] },
    },
  },
  {
    id: 'studio', title: 'Building a Home Studio',
    sort: {
      score: null, progress: 1, status: STATUS_RANK.Completed, runtime: 12.7,
      time_watched: 12, release_date: 20240101, date_added: 20250512, genres: 'How-to',
    },
    track: {
      mediaType: 'video', progressLabel: 'Times watched', progressValue: '1', progressMax: 1,
      startDate: '2025-05-12', endDate: '2025-05-12',
    },
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-studio/80/80', alt: 'Building a Home Studio' },
      title: { kind: 'title', text: 'Building a Home Studio', href: '#open:studio' },
      media_type: { kind: 'text', text: 'Video', muted: true },
      score: { kind: 'score', rated: false, text: '' },
      progress: { kind: 'text', text: '12:40 watched' },
      status: { kind: 'status', text: 'Completed' },
      runtime: { kind: 'text', text: '12:40' },
      time_watched: { kind: 'text', text: '12m' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'May 12, 2025' },
      genres: { kind: 'genres', items: [{ label: 'How-to' }] },
    },
  },
];

const TABLE_PALETTE = { ...palette, link: '#818cf8', accentContrast: '#ffffff' };

const FORM_PALETTE = {
  ...mediaCardPalette,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
  dateTime: mediaCardPalette,
};

const HOST_PALETTE = {
  ...mediaCardPalette,
  backdrop: 'rgba(24, 24, 27, 0.78)',
};

const FORM_LABELS = {
  title: 'Tracking',
  close: 'Close',
  save: 'Save',
  delete: 'Delete',
  required: '%s is required.',
  invalidNumber: 'Enter a number.',
  minimum: 'Must be at least %s.',
  maximum: 'Must be at most %s.',
  dateOrder: 'End date must be on or after the start date.',
};

function isEmptyValue(value) {
  return value === '' || value == null;
}

function sortValue(row, key) {
  const explicit = row.sort?.[key];
  if (explicit !== undefined) {
    return explicit;
  }
  return row.cells?.[key]?.text ?? '';
}

function compareRows(left, right, key, factor) {
  const a = sortValue(left, key);
  const b = sortValue(right, key);
  if (isEmptyValue(a) || isEmptyValue(b)) {
    return isEmptyValue(a) && isEmptyValue(b) ? 0 : isEmptyValue(a) ? 1 : -1;
  }
  let result;
  if (typeof a === 'number' && typeof b === 'number') {
    result = a - b;
  } else {
    const leftText = String(a).toLowerCase();
    const rightText = String(b).toLowerCase();
    result = leftText < rightText ? -1 : leftText > rightText ? 1 : 0;
  }
  return result * factor;
}

function sortRows(rows, key, direction) {
  if (!key) {
    return rows;
  }
  const factor = direction === 'desc' ? -1 : 1;
  return [...rows].sort((left, right) => compareRows(left, right, key, factor));
}

function displayRow(row, override) {
  let next = row;
  if (override) {
    const cells = { ...row.cells };
    if (override.status !== undefined) {
      cells.status = { kind: 'status', text: override.status || '—', muted: !override.status };
    }
    if (override.score !== undefined) {
      cells.score = {
        kind: 'score',
        rated: override.score != null,
        text: override.score == null ? '' : String(override.score),
      };
    }
    next = { ...row, cells, sort: { ...row.sort, ...(override.sort || {}) } };
  }
  return {
    ...next,
    cells: {
      ...next.cells,
      actions: {
        kind: 'tags',
        items: [
          { label: 'Track', href: `#track:${row.id}` },
          { label: 'Open', href: `#open:${row.id}` },
        ],
      },
    },
  };
}

function demoTrack(row) {
  const track = row.track || {};
  const status = row.cells.status?.text;
  return normalizeTrackForm({
    title: row.title,
    titleSubtitle: `${row.cells.media_type?.text || ''} · ${row.cells.progress?.text || ''}`,
    mediaType: track.mediaType || '',
    action: '#track',
    deleteAction: status ? '#track-delete' : '',
    csrfToken: 'demo',
    submitLabel: 'Save',
    deleteLabel: 'Delete',
    fields: [
      {
        name: 'status',
        label: 'Status',
        type: 'select',
        value: STATUS_RANK[status] === undefined ? 'Planning' : status,
        required: false,
        options: STATUS_OPTIONS,
      },
      {
        name: 'score',
        label: 'Score',
        type: 'number',
        value: row.cells.score?.rated ? row.cells.score.text : '',
        min: 0,
        max: 10,
        step: 0.5,
      },
      {
        name: 'progress',
        label: track.progressLabel || 'Progress',
        type: 'number',
        value: track.progressValue ?? '',
        min: 0,
        max: track.progressMax ?? null,
      },
      { name: 'start_date', label: 'Start date', type: 'date', value: track.startDate || '' },
      { name: 'end_date', label: 'End date', type: 'date', value: track.endDate || '' },
    ],
  });
}

function QuickTrack({ row, onSave, onDelete, onClose }) {
  const model = useMemo(() => demoTrack(row), [row]);
  const [values, setValues] = useState(() => initialTrackValues(model));
  return <TrackForm
    model={model}
    values={values}
    status="ready"
    busy={false}
    labels={FORM_LABELS}
    palette={FORM_PALETTE}
    showHeader={false}
    onChange={(name, value) => setValues(current => ({ ...current, [name]: value }))}
    onSubmit={next => onSave(row, next)}
    onDelete={next => onDelete(row, next)}
    onClose={onClose} />;
}

export default function TableSlot({ onOpenDetail }) {
  const [columns, setColumns] = useState(() => COLUMNS.map(column => ({ ...column })));
  const [sort, setSort] = useState('title');
  const [direction, setDirection] = useState('asc');
  const [overrides, setOverrides] = useState({});
  const [tracking, setTracking] = useState('');

  function saveColumns({ order, hidden }) {
    const hiddenSet = new Set(hidden);
    const byKey = new Map(COLUMNS.map(column => [column.key, column]));
    const fixedOrder = COLUMNS.filter(column => column.fixed).map(column => column.key);
    const nextOrder = [...fixedOrder, ...order.filter(key => byKey.has(key) && !fixedOrder.includes(key))];
    setColumns(nextOrder.map(key => byKey.get(key)).filter(Boolean)
      .map(column => ({ ...column, visible: column.fixed ? true : !hiddenSet.has(column.key) })));
  }

  function sortBy(key) {
    const ascendingByDefault = new Set(['author', 'popularity', 'runtime', 'start_date', 'title',
      'next_episode_air_date', 'time_left', 'time_to_beat', 'platform']);
    setDirection(sort === key ? (direction === 'asc' ? 'desc' : 'asc') : (ascendingByDefault.has(key) ? 'asc' : 'desc'));
    setSort(key);
  }

  function openDetail(row) {
    onOpenDetail?.(row);
  }

  function follow(href) {
    if (!href) {
      return;
    }
    if (href.startsWith('#track:')) {
      setTracking(href.slice('#track:'.length));
      return;
    }
    const id = href.startsWith('#open:') ? href.slice('#open:'.length) : '';
    openDetail(ROWS.find(row => row.id === id) || { href });
  }

  function saveTrack(row, values) {
    const status = values.status || '';
    const score = values.score === '' || values.score == null ? null : Number(values.score);
    setOverrides(current => ({
      ...current,
      [row.id]: {
        status,
        score,
        sort: {
          status: status ? STATUS_RANK[status] : null,
          score,
        },
      },
    }));
    setTracking('');
    AccessibilityInfo.announceForAccessibility?.(`${row.title} updated`);
  }

  function removeTrack(row) {
    setOverrides(current => ({
      ...current,
      [row.id]: {
        status: '',
        score: null,
        sort: { status: null, score: null },
      },
    }));
    setTracking('');
    AccessibilityInfo.announceForAccessibility?.(`${row.title} tracking removed`);
  }

  const visibleColumns = useMemo(() => columns.filter(column => column.visible !== false), [columns]);
  const tableColumns = useMemo(() => [...visibleColumns, ACTION_COLUMN], [visibleColumns]);
  const rows = useMemo(() => sortRows(
    ROWS.map(row => displayRow(row, overrides[row.id])),
    sort,
    direction,
  ), [overrides, sort, direction]);
  const trackRow = tracking ? rows.find(row => row.id === tracking) : null;
  const sortLabel = COLUMNS.find(column => column.key === sort)?.label || sort;

  return <View style={styles.root}>
    <View style={styles.toolbar}>
      <MediaColumnMenu
        columns={columns}
        defaultOrder={COLUMNS.map(column => column.key)}
        defaultHidden={COLUMNS.filter(column => column.visible === false).map(column => column.key)}
        palette={TABLE_PALETTE}
        onSave={saveColumns} />
      <Text accessibilityRole="status" accessibilityLiveRegion="polite" style={styles.caption}>
        {`Sorted by ${sortLabel}, ${direction === 'asc' ? 'ascending' : 'descending'} · ${tableColumns.length} of ${COLUMNS.length + 1} columns · swipe the table sideways`}
      </Text>
    </View>
    <MediaTable
      columns={tableColumns}
      rows={rows}
      sort={sort}
      sortDirection={direction}
      onSort={sortBy}
      onOpen={openDetail}
      onOpenLink={follow}
      palette={TABLE_PALETTE}
      caption="Library table" />
    <MediaCardActionHost
      action={trackRow ? { title: trackRow.title } : null}
      open={!!trackRow}
      labels={{ close: 'Close' }}
      palette={HOST_PALETTE}
      onClose={() => setTracking('')}>
      {trackRow ? <QuickTrack key={trackRow.id} row={trackRow}
        onSave={saveTrack} onDelete={removeTrack} onClose={() => setTracking('')} /> : null}
    </MediaCardActionHost>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  toolbar: { gap: spacing.xs },
  caption: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
