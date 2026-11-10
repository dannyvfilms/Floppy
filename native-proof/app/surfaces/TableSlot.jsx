import React, { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { MediaTable } from '../../../frontend/ui/MediaTable';
import { MediaColumnMenu } from '../../../frontend/ui/ColumnMenu';
import { mediaCardPalette, palette, spacing } from '../theme';

export const surface = {
  id: 'TABLES',
  status: 'in_progress',
  title: 'Table view and columns',
  where: 'Library and list table layouts',
  note: 'The shared React Native media table keeps the release outer rounded outline, header rule and row separators. The Library screen supplies rows from /api/v1/media/ and the table renders configurable columns with server-side sorting through the header (the sortable columns follow the API sort options) and the columns of each library, score/status/progress/units cells and accessible horizontal scrolling. The column menu reorders and hides columns while keeping the fixed poster and title columns. In select mode each row shows a checkbox wired to the screen selection, and load more fetches the next API page. There is no Actions column, like the web table (its only row control is a hover pencil that touch screens never show); a row opens its detail page. The column choice (order and hidden columns) is stored per user through /api/v1/library/preferences/{type}/, the same data the web column menu writes. The browser interaction pass and iOS/Android runtime and accessibility passes remain.',
};

// The web table's columns for the watched types (movies, shows, anime), in
// the web's order. The same fixed poster and title columns lead every type.
const COLUMNS = [
  { key: 'image', label: '', width: 56, fixed: true, visible: true },
  { key: 'title', label: 'Title', width: 140, primary: true, fixed: true, visible: true },
  { key: 'media_type', label: 'Media Type', width: 120, align: 'center', visible: true },
  { key: 'score', label: 'Score', width: 90, align: 'center', visible: true },
  { key: 'critic_rating', label: 'Critic Rating', width: 100, align: 'center', visible: true },
  { key: 'progress', label: 'Progress', width: 130, align: 'center', visible: true },
  { key: 'runtime', label: 'Runtime', width: 100, align: 'center', visible: true },
  { key: 'time_watched', label: 'Time Watched', width: 120, align: 'center', visible: true },
  { key: 'popularity', label: 'Popularity', width: 110, align: 'center', visible: true },
  { key: 'genres', label: 'Genres', width: 160, visible: true },
  { key: 'tags', label: 'Tags', width: 90, align: 'center', visible: true },
  { key: 'status', label: 'Status', width: 120, align: 'center', visible: true },
  { key: 'release_date', label: 'Release Date', width: 130, align: 'center', visible: true },
  { key: 'date_added', label: 'Date Added', width: 130, align: 'center', visible: true },
  { key: 'start_date', label: 'Start Date', width: 130, align: 'center', visible: true },
  { key: 'end_date', label: 'End Date', width: 130, align: 'center', visible: true },
  { key: 'source', label: 'Source', width: 90, align: 'center', visible: true },
  { key: 'notes', label: 'Notes', width: 240, visible: true },
  { key: 'description', label: 'Description', width: 280, visible: true },
];

// Columns that only mean something for some libraries, like the server's sort
// guards: runtime, time watched and critic rating for watched types, progress
// for everything but movies, and the media type column only on a mixed list.
function columnsFor(mediaType) {
  const watched = ['movie', 'tv', 'anime'].includes(mediaType);
  return COLUMNS.filter(column => {
    if (column.key === 'media_type') return !mediaType;
    if (['runtime', 'time_watched', 'critic_rating'].includes(column.key)) return watched;
    if (column.key === 'progress') return mediaType !== 'movie';
    return true;
  });
}

const TABLE_PALETTE = { ...palette, link: mediaCardPalette.link, accentContrast: mediaCardPalette.chipText };

// The server names two columns differently from the row cells.
const SERVER_KEY = { source: 'entry_source', description: 'synopsis' };
const NATIVE_KEY = { entry_source: 'source', synopsis: 'description' };

// Apply the viewer's saved columns (server `columns` config: the hideable
// columns in their order with a visible flag) to the columns the rows can show.
function applyColumnConfig(available, config) {
  if (!config || !config.length) return available.map(column => ({ ...column }));
  const byKey = new Map(available.map(column => [column.key, column]));
  const fixed = available.filter(column => column.fixed);
  const ordered = [];
  const visibility = new Map();
  for (const entry of config) {
    const key = NATIVE_KEY[entry.key] || entry.key;
    if (byKey.has(key) && !byKey.get(key).fixed && !visibility.has(key)) {
      ordered.push(key);
      visibility.set(key, entry.visible !== false);
    }
  }
  const rest = available.filter(column => !column.fixed && !visibility.has(column.key));
  return [
    ...fixed.map(column => ({ ...column })),
    ...ordered.map(key => ({ ...byKey.get(key), visible: visibility.get(key) })),
    ...rest.map(column => ({ ...column, visible: column.visible !== false })),
  ];
}

export default function TableSlot({
  rows = [],
  selectMode = false,
  selectedIds = [],
  onToggleItem,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  onOpenDetail,
  columnConfig,
  onColumnsSave,
  mediaType,
  sort,
  direction = 'desc',
  sortableKeys = [],
  onSortChange,
}) {
  const available = useMemo(() => columnsFor(mediaType), [mediaType]);
  const [columns, setColumns] = useState(() => applyColumnConfig(available, columnConfig));
  const [applied, setApplied] = useState(columnConfig);
  if (applied !== columnConfig) {
    // The viewer's saved columns arrive after the page loads.
    setApplied(columnConfig);
    setColumns(applyColumnConfig(available, columnConfig));
  }

  function saveColumns({ order, hidden }) {
    const hiddenSet = new Set(hidden);
    const byKey = new Map(available.map(column => [column.key, column]));
    const fixedOrder = available.filter(column => column.fixed).map(column => column.key);
    const nextOrder = [...fixedOrder, ...order.filter(key => byKey.has(key) && !fixedOrder.includes(key))];
    setColumns(nextOrder.map(key => byKey.get(key)).filter(Boolean)
      .map(column => ({ ...column, visible: column.fixed ? true : !hiddenSet.has(column.key) })));
    onColumnsSave?.({
      order: nextOrder.filter(key => !fixedOrder.includes(key)).map(key => SERVER_KEY[key] || key),
      hidden: hidden.map(key => SERVER_KEY[key] || key),
    });
  }

  function openDetail(row) {
    onOpenDetail?.(row);
  }

  function follow(href) {
    if (!href) return;
    const id = href.startsWith('#open:') ? href.slice('#open:'.length) : '';
    openDetail(rows.find(row => row.id === id) || { href });
  }

  const visibleColumns = useMemo(() => columns.filter(column => column.visible !== false), [columns]);
  // Header sorting is the server sort: only columns the server can order by
  // are sortable, and a change reloads the page from the API.
  const tableColumns = useMemo(() => visibleColumns.map(column => ({
    ...column,
    sortable: sortableKeys.includes(column.key) && Boolean(onSortChange),
  })), [visibleColumns, sortableKeys, onSortChange]);

  return <View style={styles.root}>
    <View style={styles.toolbar}>
      <MediaColumnMenu
        columns={columns}
        defaultOrder={available.map(column => column.key)}
        defaultHidden={available.filter(column => column.visible === false).map(column => column.key)}
        palette={TABLE_PALETTE}
        compact
        onSave={saveColumns} />
    </View>
    <MediaTable
      columns={tableColumns}
      rows={rows}
      sort={sort}
      sortDirection={direction}
      onSort={onSortChange}
      onOpen={openDetail}
      onOpenLink={follow}
      palette={TABLE_PALETTE}
      selectMode={selectMode}
      selectedIds={selectedIds}
      onToggleItem={onToggleItem}
      hasMore={hasMore}
      loadingMore={loadingMore}
      onLoadMore={onLoadMore}
      caption="Library table" />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  toolbar: { gap: spacing.xs, alignItems: 'flex-end' },
});
