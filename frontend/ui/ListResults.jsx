import React, { useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { Button } from './Button';
import { MediaCard } from './MediaCard';
import { MediaTable } from './MediaTable';
import { MediaColumnMenu } from './ColumnMenu';
import { RatingStars } from './RatingStars';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  danger: '#ef4444',
};

const defaultLabels = {
  selectItem: 'Select',
  selectItems: 'Select Items',
  cancelSelect: 'Cancel Select',
  clear: 'Clear',
  selected: 'selected',
  noSelection: 'Pick items to use these actions.',
  updateStatus: 'Update Status',
  chooseStatus: 'Choose status',
  removeFromList: 'Remove from List',
  addToList: 'Add to List',
  addToCollection: 'Add to Collection',
  applyTag: 'Apply Tag',
  addPlays: 'Add Plays to History',
  noResultsTitle: 'No results found',
  noResultsSearch: "We couldn't find any matches. Try a different search or adjust your filters.",
  noResultsFilters: "We couldn't find any matches with the current filters.",
  recommend: 'Recommend Item',
  emptyTitle: 'No items in this list yet',
  emptyCopy: 'Start adding your favorite media to build your collection.',
  emptyReadOnly: 'This list is empty.',
  smartEmptyTitle: 'No matching items yet',
  smartEmptyCopy: 'Saved rules keep this list updated as your library changes.',
  browse: 'Browse Media',
  title: 'Title',
  type: 'Type',
  status: 'Status',
  score: 'Score',
  progress: 'Progress',
  released: 'Released',
  added: 'Added',
  configureColumns: 'Configure Table Columns',
  columns: 'Columns',
  moveUp: 'Move up',
  moveDown: 'Move down',
  hideColumn: 'Hide column',
  showColumn: 'Show column',
  resetColumns: 'Reset to defaults',
  alwaysShown: 'Always shown',
};

const TABLE_COLUMNS = [
  { key: 'title', label: 'title', wide: true },
  { key: 'mediaTypeLabel', label: 'type' },
  { key: 'statusLabel', label: 'status' },
  { key: 'score', label: 'score' },
  { key: 'progressLabel', label: 'progress' },
  { key: 'releaseLabel', label: 'released' },
  { key: 'addedLabel', label: 'added' },
];

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...defaultLabels, ...(labels || {}) };
}

function isSelected(selectedIds, id) {
  if (!selectedIds) {
    return false;
  }
  return typeof selectedIds.has === 'function'
    ? selectedIds.has(id)
    : selectedIds.includes(id);
}

function sortNote(item, sort) {
  switch (sort) {
    case 'end_date':
      return item.endDateLabel || null;
    case 'start_date':
      return item.startDateLabel || null;
    case 'date_added':
      return item.addedLabel || null;
    case 'custom':
      return item.rank ? `#${item.rank}` : null;
    case 'release_date':
      return item.releaseLabel || null;
    case 'progress':
      return item.progressLabel || null;
    case 'media_type':
      return item.mediaTypeLabel || null;
    default:
      return null;
  }
}

function defaultLines(item) {
  const parts = [];
  if (item.mediaTypeLabel) {
    parts.push({ text: item.mediaTypeLabel });
  }
  if (item.statusLabel) {
    parts.push({ text: ` • ${item.statusLabel}`, muted: true });
  }
  if (item.progressLabel) {
    parts.push({ text: ` • ${item.progressLabel}`, muted: true });
  }
  return parts.length ? [{ join: 'plain', parts }] : [];
}

function cardModel(item, sort, canEdit) {
  const rating = item.rating || (item.score != null
    ? { label: String(item.score), value: item.score, scaleMax: 10 }
    : null);
  return {
    mediaType: item.mediaType,
    shape: item.cardShape || 'poster',
    video: item.video || false,
    title: item.title,
    altTitle: item.altTitle || null,
    publicView: item.publicView || false,
    image: item.image || { src: null, fallback: '', source: 'primary' },
    statusChip: item.cardStatusChip || (item.status
      ? { kind: 'status', status: item.status, label: item.statusLabel }
      : null),
    cornerChips: item.cardCornerChips || [],
    titleLinks: [],
    progressBar: item.progressBar || null,
    lines: item.cardLines || defaultLines(item),
    rating,
    ratingEditable: canEdit && item.ratingEditable !== false,
    actions: canEdit ? item.cardActions || null : null,
  };
}

export function ListResultGrid({
  items,
  sort,
  palette,
  labels,
  selectedIds,
  selectMode,
  canEdit = false,
  onToggleItem,
  onOpenItem,
  onRate,
  onOpenLink,
  onAction,
  renderRating,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const { width } = useWindowDimensions();
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(184, Math.max(128, (width - 32 - (columns - 1) * 12) / columns));
  const ratingRenderer = renderRating || ((props) => <RatingStars
    scaleMax={props.scaleMax}
    value={props.value}
    label={props.label}
    onSelect={props.onSelect}
    palette={props.palette}
    renderStar={lit => <Text style={[styles.pickerStar, { color: lit ? props.palette.lit : props.palette.unlit }]}>★</Text>} />);
  return <View style={styles.grid}>
    {items.map(item => <View key={item.id} style={{ width: cardWidth }}>
      <MediaCard
        model={cardModel(item, sort, canEdit)}
        palette={{
          card: colors.surface,
          text: colors.text,
          textSecondary: colors.textSecondary,
          textMuted: colors.textMuted,
          border: colors.border,
          link: colors.accent,
          placeholder: colors.surfaceStrong,
          progressFill: colors.accent,
        }}
        width={cardWidth}
        labels={{ selectItem: copy.selectItem }}
        selection={selectMode ? {
          active: true,
          selected: isSelected(selectedIds, item.id),
          toggle: () => onToggleItem?.(item.id),
          label: `${copy.selectItem} ${item.title}`,
        } : undefined}
        onOpen={onOpenItem ? () => onOpenItem(item) : undefined}
        onRate={onRate ? score => onRate(item, score) : undefined}
        onOpenLink={onOpenLink}
        onAction={onAction ? action => onAction(item, action) : undefined}
        renderRating={ratingRenderer}
      />
      {sortNote(item, sort) ? <Text style={[styles.sortNote, { color: colors.text }]}>
        {sortNote(item, sort)}
      </Text> : null}
    </View>)}
  </View>;
}

function listTableColumns(labels) {
  return TABLE_COLUMNS.map(column => ({
    key: column.key,
    label: labels[column.label] || column.key,
    width: column.wide ? 220 : 120,
    align: column.key === 'title' ? 'left' : 'center',
    primary: !!column.wide,
    fixed: false,
  }));
}

function listTableRows(items) {
  return items.map(item => ({
    id: item.id,
    title: item.title,
    cells: {
      title: { kind: 'title', text: item.title || '—' },
      mediaTypeLabel: { kind: 'text', text: item.mediaTypeLabel || '—' },
      statusLabel: { kind: 'status', text: item.statusLabel || '—', muted: !item.statusLabel },
      score: {
        kind: 'score',
        rated: item.score != null,
        text: item.score != null ? String(item.score) : '',
      },
      progressLabel: { kind: 'progress', text: item.progressLabel || '—' },
      releaseLabel: { kind: 'text', text: item.releaseLabel || '—', muted: !item.releaseLabel },
      addedLabel: { kind: 'text', text: item.addedLabel || '—', muted: !item.addedLabel },
    },
  }));
}

export function ListResultTable({
  items,
  palette,
  labels,
  selectedIds,
  selectMode,
  onToggleItem,
  onOpenItem,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [columns, setColumns] = useState(() => listTableColumns(copy));
  function saveColumns({ order, hidden }) {
    const hiddenSet = new Set(hidden);
    const byKey = new Map(columns.map(column => [column.key, column]));
    setColumns(order.map(key => byKey.get(key)).filter(Boolean)
      .map(column => ({ ...column, visible: !hiddenSet.has(column.key) })));
  }
  return <View style={styles.results}>
    <MediaColumnMenu
      columns={columns}
      defaultOrder={TABLE_COLUMNS.map(column => column.key)}
      defaultHidden={[]}
      palette={colors}
      labels={{
        configure: copy.configureColumns,
        columns: copy.columns,
        moveUp: copy.moveUp,
        moveDown: copy.moveDown,
        hide: copy.hideColumn,
        show: copy.showColumn,
        reset: copy.resetColumns,
        alwaysShown: copy.alwaysShown,
      }}
      onSave={saveColumns} />
    <MediaTable
      columns={columns.filter(column => column.visible !== false)}
      rows={listTableRows(items)}
      palette={colors}
      labels={copy}
      selectMode={selectMode}
      selectedIds={selectedIds}
      onToggleItem={onToggleItem}
      onOpen={onOpenItem ? item => onOpenItem(items.find(entry => entry.id === item.id)) : undefined} />
  </View>;
}

export function ListBulkBar({
  count = 0,
  palette,
  labels,
  statuses = [],
  onClear,
  onAction,
  onRemove,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [statusOpen, setStatusOpen] = useState(false);
  const actions = [
    { kind: 'status', label: copy.updateStatus, tone: 'primary' },
    { kind: 'list', label: copy.addToList, tone: 'surface' },
    { kind: 'collection', label: copy.addToCollection, tone: 'surface' },
    { kind: 'tag', label: copy.applyTag, tone: 'surface' },
    { kind: 'plays', label: copy.addPlays, tone: 'surface' },
  ];
  function choose(action) {
    if (action.kind === 'status' && statuses.length > 0) {
      setStatusOpen(current => !current);
      return;
    }
    onAction?.(action.kind);
  }
  return <View accessible accessibilityLabel="Bulk actions"
    style={[styles.bulkBar, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.bulkHeader}>
      <Text style={[styles.bulkCount, { color: colors.text }]}>
        <Text style={{ fontWeight: '700' }}>{count}</Text> {copy.selected}
      </Text>
      <Button label={copy.clear} tone="surface" onPress={onClear} />
    </View>
    {count === 0 ? <Text style={[styles.bulkHint, { color: colors.textMuted }]}>
      {copy.noSelection}
    </Text> : null}
    <View style={styles.bulkActions}>
      {actions.map(action => <Button key={action.kind}
        label={action.label}
        tone={action.tone}
        disabled={count === 0}
        onPress={() => choose(action)} />)}
      {onRemove ? <Button
        label={copy.removeFromList}
        tone="ghost-danger"
        disabled={count === 0}
        onPress={onRemove} /> : null}
    </View>
    {statusOpen ? <View style={styles.bulkActions} accessible accessibilityLabel={copy.chooseStatus}>
      {statuses.map(status => <Button key={status.value}
        label={status.label}
        tone="surface"
        onPress={() => {
          setStatusOpen(false);
          onAction?.('status', status.value);
        }} />)}
    </View> : null}
  </View>;
}

export function ListEmptyState({
  mode = 'empty',
  hasSearch = false,
  canEdit = false,
  canRecommend = false,
  isSmart = false,
  palette,
  labels,
  onBrowse,
  onRecommend,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const smart = isSmart || mode === 'smart';
  const title = smart
    ? copy.smartEmptyTitle
    : mode === 'search' || mode === 'filters' ? copy.noResultsTitle : copy.emptyTitle;
  const description = smart
    ? copy.smartEmptyCopy
    : mode === 'search' ? copy.noResultsSearch
      : mode === 'filters' ? copy.noResultsFilters
        : canEdit ? copy.emptyCopy : copy.emptyReadOnly;
  return <View style={[styles.empty, { backgroundColor: colors.surface }]}>
    <Text style={[styles.emptyTitle, { color: colors.text }]}>{title}</Text>
    <Text style={[styles.emptyCopy, { color: colors.textMuted }]}>{description}</Text>
    {canEdit && mode === 'empty' ? <Button label={copy.browse} tone="primary"
      onPress={onBrowse} /> : null}
    {canRecommend ? <Button label={copy.recommend} tone="surface"
      onPress={onRecommend} /> : null}
  </View>;
}

export function ListResults({
  items,
  layout = 'grid',
  sort = 'date_added',
  palette,
  labels,
  canEdit = false,
  canRecommend = false,
  isSmart = false,
  selectMode = false,
  selectedIds = [],
  onToggleItem,
  onToggleSelectMode,
  onClearSelection,
  onBulkAction,
  bulkStatuses = [],
  onRemoveItems,
  bulkMessage,
  onOpenItem,
  onRate,
  onOpenLink,
  onAction,
  renderRating,
  emptyMode,
  hasSearch = false,
  onBrowse,
  onRecommend,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [ratings, setRatings] = useState({});
  const shownItems = items.map(item => ratings[item.id] === undefined
    ? item
    : {
        ...item,
        rating: {
          ...(item.rating || { scaleMax: 10 }),
          value: ratings[item.id],
          label: ratings[item.id] == null ? null : String(ratings[item.id]),
        },
      });
  const rate = (item, score) => {
    setRatings(current => ({ ...current, [item.id]: score }));
    onRate?.(item, score);
  };
  const mode = emptyMode || (hasSearch ? 'search' : 'empty');
  return <View style={styles.results}>
    {canEdit ? <View style={styles.selectRow}>
      <Button
        label={selectMode ? copy.cancelSelect : copy.selectItems}
        tone="surface"
        onPress={onToggleSelectMode} />
    </View> : null}
    {selectMode ? <ListBulkBar
      count={selectedIds.length}
      palette={colors}
      labels={copy}
      statuses={bulkStatuses}
      onClear={onClearSelection}
      onAction={onBulkAction}
      onRemove={onRemoveItems ? () => onRemoveItems(selectedIds) : undefined} /> : null}
    {bulkMessage ? <Text style={[styles.bulkMessage, { color: colors.textMuted }]}>
      {bulkMessage}
    </Text> : null}
    {shownItems.length === 0
      ? <ListEmptyState
          mode={mode}
          hasSearch={hasSearch}
          canEdit={canEdit}
          canRecommend={canRecommend}
          isSmart={isSmart}
          palette={colors}
          labels={copy}
          onBrowse={onBrowse}
          onRecommend={onRecommend} />
      : layout === 'table'
        ? <ListResultTable
            items={shownItems}
            palette={colors}
            labels={copy}
            selectMode={selectMode}
            selectedIds={selectedIds}
            onToggleItem={onToggleItem}
            onOpenItem={onOpenItem} />
        : <ListResultGrid
            items={shownItems}
            sort={sort}
            palette={colors}
            labels={copy}
            canEdit={canEdit}
            selectMode={selectMode}
            selectedIds={selectedIds}
            onToggleItem={onToggleItem}
            onOpenItem={onOpenItem}
            onRate={rate}
            onOpenLink={onOpenLink}
            onAction={onAction}
            renderRating={renderRating} />}
  </View>;
}

const styles = StyleSheet.create({
  results: { gap: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  pickerStar: { fontSize: 20 },
  sortNote: { fontSize: 12, fontWeight: '600', marginTop: 6 },
  selectRow: { flexDirection: 'row', justifyContent: 'flex-end' },
  bulkBar: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 8 },
  bulkHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  bulkCount: { fontSize: 13 },
  bulkHint: { fontSize: 12 },
  bulkActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  bulkMessage: { fontSize: 12 },
  empty: { borderRadius: 10, paddingVertical: 40, paddingHorizontal: 20, gap: 10, alignItems: 'center' },
  emptyTitle: { fontSize: 18, fontWeight: '600', textAlign: 'center' },
  emptyCopy: { fontSize: 13, lineHeight: 19, textAlign: 'center', maxWidth: 420 },
  tableScroll: { paddingBottom: 4 },
  table: { minWidth: 720 },
  tableRow: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1, paddingVertical: 10, paddingHorizontal: 8, gap: 8 },
  tableHeader: { borderTopWidth: 0 },
  checkColumn: { width: 28, alignItems: 'center', justifyContent: 'center' },
  checkText: { fontSize: 16, fontWeight: '700' },
  cell: { width: 92, paddingHorizontal: 4 },
  wideCell: { width: 200, flexGrow: 1 },
  headerCell: { fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.4 },
  cellText: { fontSize: 13 },
});
