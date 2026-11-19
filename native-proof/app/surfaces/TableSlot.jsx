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
  note: 'The shared React Native media table keeps the release outer rounded outline, header rule and row separators. The Library screen supplies rows from /api/v1/media/ and the table renders configurable columns with real client-side sorting (title, media type, score, progress, status, runtime, time watched, release and added dates, genres), score/status/progress/units cells and accessible horizontal scrolling. The column menu reorders and hides columns while keeping the fixed poster and title columns. Each row exposes Track and Open actions: Track opens the shared tracking form and updates that row status and score in local state, and Open follows the row detail route. Track saves PATCH the row provider identity and the delete action removes it through /api/v1/media/{type}/{source}/{id}/; the browser interaction pass and iOS/Android runtime and accessibility passes remain.',
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

// Apply the viewer's saved columns (server `columns` config: the hideable
// columns in their order with a visible flag) to the columns the rows can show.
function applyColumnConfig(config) {
  if (!config || !config.length) return COLUMNS.map(column => ({ ...column }));
  const byKey = new Map(COLUMNS.map(column => [column.key, column]));
  const ordered = [];
  const visibility = new Map();
  for (const entry of config) {
    if (byKey.has(entry.key) && !byKey.get(entry.key).fixed && !visibility.has(entry.key)) {
      ordered.push(entry.key);
      visibility.set(entry.key, entry.visible !== false);
    }
  }
  return [
    ...COLUMNS.filter(column => column.fixed).map(column => ({ ...column })),
    // Columns the server does not store keep their place ahead of the stored ones.
    ...COLUMNS.filter(column => !column.fixed && !visibility.has(column.key)).map(column => ({ ...column })),
    ...ordered.map(key => ({ ...byKey.get(key), visible: visibility.get(key) })),
  ];
}

export default function TableSlot({ rows = [], onOpenDetail, onTrackSave, onTrackDelete,
  selecting = false, selectedRows = [], onToggleSelect, querySort, queryDirection, onQuerySort,
  columnConfig, onColumnsSave }) {
  const [columns, setColumns] = useState(() => applyColumnConfig(columnConfig));
  const [applied, setApplied] = useState(columnConfig);
  if (applied !== columnConfig) {
    // The viewer's saved columns arrive after the page loads.
    setApplied(columnConfig);
    setColumns(applyColumnConfig(columnConfig));
  }
  const [localSort, setLocalSort] = useState('title');
  const [localDirection, setLocalDirection] = useState('asc');
  const sort = querySort || localSort;
  const direction = queryDirection || localDirection;
  const [overrides, setOverrides] = useState({});
  const [tracking, setTracking] = useState('');

  function saveColumns({ order, hidden }) {
    const hiddenSet = new Set(hidden);
    const byKey = new Map(COLUMNS.map(column => [column.key, column]));
    const fixedOrder = COLUMNS.filter(column => column.fixed).map(column => column.key);
    const nextOrder = [...fixedOrder, ...order.filter(key => byKey.has(key) && !fixedOrder.includes(key))];
    setColumns(nextOrder.map(key => byKey.get(key)).filter(Boolean)
      .map(column => ({ ...column, visible: column.fixed ? true : !hiddenSet.has(column.key) })));
    // The column choice is stored per user, the same data the web column menu writes.
    const stored = new Set((columnConfig || []).map(entry => entry.key));
    if (onColumnsSave && stored.size) {
      onColumnsSave({
        order: nextOrder.filter(key => stored.has(key)),
        hidden: hidden.filter(key => stored.has(key)),
      });
    }
  }

  function sortBy(key) {
    const ascendingByDefault = new Set(['author', 'popularity', 'runtime', 'start_date', 'title',
      'next_episode_air_date', 'time_left', 'time_to_beat', 'platform']);
    const nextDirection = sort === key ? (direction === 'asc' ? 'desc' : 'asc')
      : ascendingByDefault.has(key) ? 'asc' : 'desc';
    if (onQuerySort) onQuerySort(key, nextDirection);
    else {
      setLocalDirection(nextDirection);
      setLocalSort(key);
    }
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
    openDetail(rows.find(row => row.id === id) || { href });
  }

  async function saveTrack(row, values) {
    const status = values.status || '';
    const score = values.score === '' || values.score == null ? null : Number(values.score);
    try {
      if (onTrackSave) await onTrackSave(row, values);
    } catch (cause) {
      AccessibilityInfo.announceForAccessibility?.(cause?.message || `${row.title} could not be updated`);
      return;
    }
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

  async function removeTrack(row) {
    try {
      if (onTrackDelete) await onTrackDelete(row);
    } catch (cause) {
      AccessibilityInfo.announceForAccessibility?.(cause?.message || `${row.title} could not be removed`);
      return;
    }
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
  const sortedRows = useMemo(() => sortRows(
    rows.map(row => displayRow(row, overrides[row.id])),
    sort,
    direction,
  ), [rows, overrides, sort, direction]);
  const trackRow = tracking ? sortedRows.find(row => row.id === tracking) : null;
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
      rows={sortedRows}
      sort={sort}
      sortDirection={direction}
      onSort={sortBy}
      onOpen={openDetail}
      onOpenLink={follow}
      selectMode={selecting}
      selectedIds={selectedRows}
      onToggleItem={onToggleSelect}
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
