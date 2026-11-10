import { Modal, ModalCloseButton } from './Modal';
import { Icon, SearchIcon } from './Icon';
import { actionIcons } from './actionIcons';
import React, { useMemo, useState } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { MediaCard } from './MediaCard';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  danger: '#ef4444',
  success: '#4ade80',
  radius: 10,
  radiusSmall: 6,
  overlay: 'rgba(9, 9, 11, 0.72)',
};

const DEFAULT_LABELS = {
  search: 'Search your collection',
  searchPlaceholder: 'Search your collection...',
  filters: 'Filters',
  status: 'Completeness',
  sort: 'Sort',
  view: 'View',
  allTypes: 'All Types',
  allStatuses: 'Any completeness',
  any: 'Any',
  clear: 'Clear',
  clearAll: 'Clear all filters',
  title: 'Title',
  type: 'Type',
  format: 'Format',
  resolution: 'Resolution',
  collected: 'Collected',
  completeness: 'Completeness',
  partial: 'Partial',
  full: 'Full',
  grid: 'Grid',
  rows: 'Rows',
  table: 'Table',
  empty: 'No copies match these filters.',
  emptyHint: 'Try adjusting the collection filters.',
  loadMore: 'Load more',
  editCopies: 'Open copies',
  copy: 'copy',
  copies: 'copies',
  results: 'items',
  close: 'Close',
  customField: 'Custom field',
  rating: 'Rating',
  location: 'Location',
  hdr: 'HDR',
  formatFilter: 'Format',
  resolutionFilter: 'Resolution',
  ratingAny: 'Any',
  ratingRated: 'Rated',
  ratingUnrated: 'Not Rated',
  all: 'All',
  active: 'Active',
  back: 'Back',
  anyFormat: 'Any Format',
  anyResolution: 'Any Resolution',
  anyHdr: 'Any HDR',
  anyLocation: 'Any Location',
  anyRating: 'Any Rating',
  partiallyCollected: 'Partially Collected',
  fullyCollected: 'Fully Collected',
  ascending: 'Ascending',
  descending: 'Descending',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function filterCount(filters) {
  return [
    filters.type && filters.type !== 'all',
    filters.format && filters.format !== 'all',
    filters.resolution && filters.resolution !== 'all',
    filters.hdr && filters.hdr !== 'all',
    filters.location && filters.location !== 'all',
    filters.rating && filters.rating !== 'all',
    filters.completeness && filters.completeness !== 'all',
    filters.customValue,
  ].filter(Boolean).length;
}

function mediaShape(mediaType) {
  if (mediaType === 'music' || mediaType === 'podcast') return 'square';
  if (mediaType === 'video' || mediaType === 'game') return 'landscape';
  return 'poster';
}

function copyLine(item) {
  const parts = [item.format, item.resolution, item.hdr].filter(Boolean);
  return parts.length ? parts.join(' · ') : item.mediaTypeLabel || item.mediaType;
}

function cardModel(item) {
  if (item.card) return item.card;
  const completeness = item.completeness;
  const corner = [];
  if (completeness && completeness.total) {
    corner.push({
      kind: 'collected',
      text: completeness.isPartial
        ? `${completeness.collected}/${completeness.total} · Partial`
        : `${completeness.collected}/${completeness.total} · Full`,
      title: completeness.isPartial
        ? `${completeness.collected} of ${completeness.total} episodes collected`
        : `${completeness.total} of ${completeness.total} episodes collected`,
    });
  } else if (item.copyLabel) {
    corner.push({ kind: 'queue', text: item.copyLabel });
  }
  return {
    mediaType: item.mediaType,
    identity: item.identity,
    shape: item.shape || mediaShape(item.mediaType),
    video: item.mediaType === 'video' || item.mediaType === 'movie',
    href: item.href || '',
    image: item.image,
    title: item.title,
    altTitle: item.altTitle || null,
    statusChip: {
      kind: 'media-type',
      type: item.mediaType,
      style: 'soft',
      color: item.mediaTypeColor || DEFAULT_PALETTE.accent,
      contrast: '#ffffff',
      label: item.mediaTypeLabel || item.mediaType,
    },
    cornerChips: corner,
    titleLinks: [],
    progressBar: null,
    lines: [{
      join: 'plain',
      parts: [
        { text: copyLine(item) },
        ...(item.copyLabel ? [{ text: `• ${item.copyLabel}`, muted: true }] : []),
      ],
    }],
    rating: item.rating == null ? null : {
      label: String(item.rating),
      value: item.rating,
      scaleMax: 10,
      rateLabel: 'Rate',
    },
    ratingEditable: false,
    actions: null,
  };
}

function SheetFrame({ title, labels, palette, onBack, onClose, children }) {
  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.close}
        style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={[styles.sheet, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <View style={[styles.sheetHeader, { borderColor: palette.border }]}>
          {onBack ? <Pressable accessibilityRole="button" accessibilityLabel={labels.back} onPress={onBack}
            style={styles.close}><Icon spec={actionIcons.chevronLeft} color={palette.textMuted} size={16} /></Pressable> : null}
          <Text accessibilityRole="header" style={[styles.sheetTitle, { color: palette.textSecondary }]}>{title}</Text>
          <ModalCloseButton accessibilityRole="button" accessibilityLabel={labels.close} onPress={onClose}
            style={styles.close}>
            <Icon spec={actionIcons.x} color={palette.textMuted} size={16}><Text style={[styles.closeText, { color: palette.textMuted }]}>×</Text></Icon>
          </ModalCloseButton>
        </View>
        <ScrollView style={styles.menuList} contentContainerStyle={styles.menuContent}>{children}</ScrollView>
      </View>
    </View>
  </Modal>;
}

function MenuRow({ label, value, selected, chevron, checkbox, disabled, palette, onPress }) {
  return <Pressable accessibilityRole={chevron ? 'button' : checkbox ? 'checkbox' : 'radio'} accessibilityLabel={label}
    aria-checked={chevron ? undefined : !!selected} disabled={disabled}
    accessibilityState={chevron ? undefined : { checked: !!selected, disabled: !!disabled }}
    onPress={onPress}
    style={({ pressed }) => [styles.menuRow, { backgroundColor: pressed ? palette.surfaceStrong : 'transparent', opacity: disabled ? 0.4 : 1 }]}>
    <Text numberOfLines={1} style={[styles.menuText, { color: palette.textSecondary }]}>{label}</Text>
    {value ? <Text numberOfLines={1} style={[styles.menuValue, { color: palette.textMuted }]}>{value}</Text> : null}
    {chevron ? <Icon spec={actionIcons.chevronRight} color={palette.textMuted} size={14} /> : null}
    {selected ? <Icon spec={actionIcons.checkmark} color={palette.success} size={16}>
      <Text style={[styles.check, { color: palette.success }]}>✓</Text>
    </Icon> : null}
  </Pressable>;
}

const DEFAULT_TABLE_COLUMNS = ['title', 'type', 'format', 'resolution', 'collected'];

function tableColumnLabel(column, labels) {
  return labels[column] || column;
}

function tableCellValue(item, column, labels) {
  if (column === 'type') return item.mediaTypeLabel || item.mediaType || '-';
  if (column === 'format') return item.format || '-';
  if (column === 'resolution') return item.resolution || '-';
  if (column === 'collected') return item.collectedAtLabel || item.collectedAt || '-';
  if (column === 'hdr') return item.hdr || '-';
  if (column === 'location') return item.purchaseLocation || '-';
  return item[column] == null ? '-' : String(item[column]);
}

// A host that opens detail pages opens it from the row, like the web table;
// the copy dialog stays behind the card action.
function TableView({ items, labels, palette, columns, onOpenCopy, onOpenItem }) {
  const visibleColumns = columns?.length ? columns : DEFAULT_TABLE_COLUMNS;
  return <View style={[styles.table, { borderColor: palette.border, backgroundColor: palette.surface }]}>
    <View style={[styles.tableHeader, { borderColor: palette.border }]}>
      {visibleColumns.map(column =>
        <Text key={column} style={[styles.tableHeaderText, column === 'title' ? styles.tableTitleHead : styles.tableCell, { color: palette.textMuted }]}>
          {tableColumnLabel(column, labels)}
        </Text>)}
    </View>
    {items.map(item => {
      const image = item.card?.image || item.image || {};
      return <Pressable key={item.id} accessibilityRole="button"
        accessibilityLabel={onOpenItem ? item.title : `${item.title} ${labels.editCopies}`}
        onPress={() => (onOpenItem ? onOpenItem(item) : onOpenCopy?.(item))}
        style={({ pressed }) => [styles.tableRow, {
          borderColor: palette.border,
          backgroundColor: pressed ? palette.surfaceStrong : 'transparent',
        }]}>
        {visibleColumns.map(column => column === 'title'
          ? <View key={column} style={styles.tableTitleCell}>
            <View style={styles.tableTitleRow}>
              {image.src ? <Image source={{ uri: image.src }} style={[styles.tableArtwork, { backgroundColor: palette.surfaceStrong }]}
                resizeMode="cover" accessible={false} /> : null}
              <View style={styles.tableTitleBody}>
                <Text numberOfLines={1} style={[styles.tableTitle, { color: palette.text }]}>{item.title}</Text>
                <View style={styles.badgeRow}>
                  {item.copyLabel ? <Badge label={item.copyLabel} size="xs" tone="outline" nowrap palette={{
                    outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
                  }} /> : null}
                  {item.completeness?.isPartial ? <Badge
                    label={`${item.completeness.collected}/${item.completeness.total} · ${labels.partial}`}
                    size="xs" nowrap palette={{
                      outline: { color: palette.warning || '#fbbf24', borderColor: palette.surfaceMuted, borderWidth: 1 },
                    }} /> : null}
                </View>
              </View>
            </View>
          </View>
          : <Text key={column} numberOfLines={1} style={[styles.tableCell, { color: palette.textMuted }]}>
            {tableCellValue(item, column, labels)}
          </Text>)}
      </Pressable>;
    })}
  </View>;
}

// A host that opens detail pages (onOpenItem) keeps the copy dialog behind a
// card action; otherwise a card tap opens the copy dialog.
function cardHandlers(item, labels, onOpenCopy, onOpenItem) {
  if (!onOpenItem) return { onOpen: () => onOpenCopy?.(item) };
  return {
    onOpen: () => onOpenItem(item),
    onAction: () => onOpenCopy?.(item),
    actions: {
      title: labels.open || 'Open',
      ordering: null,
      clickable: true,
      items: [{ kind: 'action', key: 'copies', title: labels.editCopies || 'Open copies', icon: actionIcons.edit, tone: 'indigo' }],
    },
  };
}

function GridView({ items, labels, palette, onOpenCopy, onOpenItem, renderCard }) {
  return <View style={styles.grid}>
    {items.map(item => <View key={item.id} style={styles.gridItem}>
      {renderCard ? renderCard(item) : <MediaCard model={cardModel(item)} width={164} palette={{
        ...palette,
        card: palette.surface,
        link: '#818cf8',
        star: '#facc15',
      }} labels={labels} {...cardHandlers(item, labels, onOpenCopy, onOpenItem)} />}
    </View>)}
  </View>;
}

function RowView({ items, groups, labels, palette, onOpenCopy, onOpenItem, onLoadMoreGroup, renderCard }) {
  const resolvedGroups = useMemo(() => {
    if (groups?.length) return groups;
    const byType = new Map();
    items.forEach(item => {
      const key = item.mediaType || 'other';
      if (!byType.has(key)) byType.set(key, []);
      byType.get(key).push(item);
    });
    return [...byType.entries()].map(([type, rows]) => ({
      key: type,
      label: rows[0]?.mediaTypeLabel || type,
      items: rows,
    }));
  }, [items, groups]);
  return <View style={styles.rows}>
    {resolvedGroups.map(group => {
      const rows = group.items || [];
      const loaded = group.loadedCount ?? rows.length;
      const countLabel = group.total == null ? loaded : `${loaded}/${group.total}`;
      return <View key={group.key || group.type} style={styles.rowGroup}>
        <View style={styles.rowHeadingRow}>
          <Text style={[styles.rowHeading, { color: palette.textSecondary }]}>
            {group.label || group.type} · {countLabel}
          </Text>
          {group.hasMore || group.loadingMore ? <Button
            label={labels.loadMore}
            tone="surface"
            palette={palette}
            busy={group.loadingMore}
            disabled={group.loadingMore}
            onPress={() => onLoadMoreGroup?.(group)} /> : null}
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.rowScroll}>
          {rows.map(item => <View key={item.id} style={styles.rowCard}>
            {renderCard ? renderCard(item) : <MediaCard model={cardModel(item)} width={164} palette={{
              ...palette,
              card: palette.surface,
              link: '#818cf8',
              star: '#facc15',
            }} labels={labels} {...cardHandlers(item, labels, onOpenCopy, onOpenItem)} />}
          </View>)}
        </ScrollView>
      </View>;
    })}
  </View>;
}

export function CollectionBrowser({
  items = [],
  groups = null,
  filters = {},
  options = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  busy = false,
  chrome = true,
  resultCount,
  hasMore = false,
  loadingMore = false,
  tableColumns,
  onFilterChange,
  onOpenCopy,
  onOpenItem,
  onLoadMore,
  onLoadMoreGroup,
  renderCard,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  const [menu, setMenu] = useState(null);
  const [searching, setSearching] = useState(false);
  const activeCount = filterCount(filters);
  const view = filters.view || 'grid';
  const grouped = options.groupByMediaType && filters.groupByMediaType && view === 'grid' && (!filters.type || filters.type === 'all');

  const filterEntries = [
    { key: 'type', title: labels.type, value: filters.type, any: labels.allTypes, options: options.mediaTypes || [] },
    options.formats?.length ? { key: 'format', title: labels.formatFilter, value: filters.format, any: labels.anyFormat, options: options.formats } : null,
    options.resolutions?.length ? { key: 'resolution', title: labels.resolutionFilter, value: filters.resolution, any: labels.anyResolution, options: options.resolutions } : null,
    options.hdrs?.length ? { key: 'hdr', title: labels.hdr, value: filters.hdr, any: labels.anyHdr, options: options.hdrs } : null,
    options.customFilter ? {
      key: 'custom',
      title: options.customFilter.label || labels.customField,
      value: filters.customValue,
      any: labels.any,
      options: options.customFilter.choices || [],
    } : null,
    options.locations?.length ? { key: 'location', title: labels.location, value: filters.location, any: labels.anyLocation, options: options.locations } : null,
    {
      key: 'rating',
      title: labels.rating,
      value: filters.rating,
      any: labels.anyRating,
      options: [
        { value: 'rated', label: labels.ratingRated },
        { value: 'not_rated', label: labels.ratingUnrated },
      ],
    },
    options.showCompleteness ? {
      key: 'completeness',
      title: labels.completeness,
      value: filters.completeness,
      any: labels.any,
      options: [
        { value: 'partial', label: labels.partiallyCollected },
        { value: 'full', label: labels.fullyCollected },
      ],
    } : null,
  ].filter(Boolean);

  function entryLabel(entry) {
    const selected = entry.value && entry.value !== 'all'
      ? entry.options.find(option => String(option.value) === String(entry.value))?.label || entry.value
      : null;
    return selected || (entry.key === 'type' ? labels.allTypes : labels.any);
  }

  function chooseEntry(entry, value) {
    setMenu(null);
    if (entry.key === 'type') onFilterChange?.({ type: 'type', value: value || 'all' });
    else if (entry.key === 'completeness') onFilterChange?.({ type: 'completeness', value: value || 'all' });
    else if (entry.key === 'custom') {
      onFilterChange?.({ type: 'set', key: 'customFilter', value: value ? options.customFilter?.id || '' : '' });
      onFilterChange?.({ type: 'set', key: 'customValue', value });
    } else onFilterChange?.({ type: 'set', key: entry.key, value: value || 'all' });
  }

  function chooseSort(value) {
    setMenu(null);
    if (value === (filters.sort || 'collected_at')) {
      onFilterChange?.({ type: 'set', key: 'direction', value: (filters.direction || 'desc') === 'asc' ? 'desc' : 'asc' });
    } else onFilterChange?.({ type: 'set', key: 'sort', value });
  }

  const sortLabel = (options.sorts || []).find(sort => sort.value === (filters.sort || 'collected_at'))?.label || labels.sort;
  const activeEntry = menu && menu.kind === 'entry' ? filterEntries.find(entry => entry.key === menu.key) : null;
  const toolbarButton = (pressed, active) => [styles.toolButton, {
    backgroundColor: active ? palette.accentStrong : pressed ? palette.surfaceStrong : 'transparent',
  }];

  return <View style={styles.root}>
    {chrome ? <View style={styles.toolbar}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.search}
        accessibilityState={{ expanded: searching }}
        onPress={() => setSearching(current => !current)}
        style={({ pressed }) => toolbarButton(pressed, false)}>
        <SearchIcon color={palette.textSecondary} size={20} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.filters}
        onPress={() => setMenu({ kind: 'filters' })}
        style={({ pressed }) => toolbarButton(pressed, false)}>
        <Icon spec={actionIcons.funnel} color={palette.textSecondary} size={16} />
        <Text style={[styles.toolText, { color: palette.textSecondary }]}>
          {labels.filters}{activeCount ? ` (${activeCount})` : ''}
        </Text>
        <Icon spec={actionIcons.chevronDown} color={palette.textMuted} size={14} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={`${labels.sort}: ${sortLabel}`}
        onPress={() => setMenu({ kind: 'sort' })}
        style={({ pressed }) => [...toolbarButton(pressed, false), styles.sortButton]}>
        <Text numberOfLines={1} style={[styles.toolText, { color: palette.textSecondary }]}>{sortLabel}</Text>
        <Icon spec={actionIcons.chevronDown} color={palette.textMuted} size={14} />
      </Pressable>
      <View style={[styles.viewToggle, { borderColor: palette.border }]}>
        {[['grid', labels.grid, actionIcons.fourSquare], ['table', labels.table, actionIcons.table]].map(([value, label, spec]) =>
          <Pressable key={value} accessibilityRole="button" accessibilityLabel={label}
            accessibilityState={{ selected: view === value }}
            onPress={() => onFilterChange?.({ type: 'set', key: 'view', value })}
            style={[styles.viewButton, { backgroundColor: view === value ? palette.accentStrong : palette.surfaceStrong }]}>
            <Icon spec={spec} color={view === value ? palette.accentContrast : palette.textSecondary} size={18} />
          </Pressable>)}
      </View>
    </View> : null}

    {chrome && (searching || filters.query) ? <View style={[styles.searchRow, { borderColor: palette.border, backgroundColor: palette.surface }]}>
      <SearchIcon color={palette.textMuted} size={20} />
      <TextInput
        accessibilityLabel={labels.search}
        value={filters.query || ''}
        onChangeText={value => onFilterChange?.({ type: 'set', key: 'query', value })}
        placeholder={labels.searchPlaceholder}
        placeholderTextColor={palette.textMuted}
        selectionColor={palette.accent}
        style={[styles.searchInput, { color: palette.text }]} />
      {filters.query ? <Pressable accessibilityRole="button" accessibilityLabel={labels.clear}
        onPress={() => onFilterChange?.({ type: 'set', key: 'query', value: '' })}>
        <Text style={[styles.searchClear, { color: palette.textMuted }]}>×</Text>
      </Pressable> : null}
    </View> : null}

    {items.length === 0 && !groups?.length ? <View style={[styles.empty, { borderColor: palette.border, backgroundColor: palette.surface }]}>
      <Text style={[styles.emptyTitle, { color: palette.text }]}>{labels.empty}</Text>
      <Text style={[styles.emptyHint, { color: palette.textMuted }]}>{labels.emptyHint}</Text>
    </View> : view === 'table'
      ? <TableView items={items} labels={labels} palette={palette} columns={tableColumns} onOpenCopy={onOpenCopy} onOpenItem={onOpenItem} />
      : view === 'rows' || grouped
        ? <RowView items={items} groups={groups} labels={labels} palette={palette}
          onOpenCopy={onOpenCopy} onOpenItem={onOpenItem} onLoadMoreGroup={onLoadMoreGroup} renderCard={renderCard} />
        : <GridView items={items} labels={labels} palette={palette} onOpenCopy={onOpenCopy} onOpenItem={onOpenItem} renderCard={renderCard} />}

    {!groups?.length && (hasMore || loadingMore) ? <View style={styles.loadMore} testID="collection-load-more">
      <Button label={labels.loadMore} tone="surface" palette={palette}
        busy={loadingMore} disabled={loadingMore} onPress={onLoadMore} />
    </View> : null}

    {menu?.kind === 'filters' ? <SheetFrame title={labels.filters} labels={labels} palette={palette} onClose={() => setMenu(null)}>
      <MenuRow label={labels.all} value={activeCount ? '' : labels.active} selected={!activeCount} palette={palette}
        onPress={() => { setMenu(null); onFilterChange?.({ type: 'reset' }); }} />
      {filterEntries.map(entry => <MenuRow key={entry.key} label={entry.title} value={entryLabel(entry)} chevron
        palette={palette} onPress={() => setMenu({ kind: 'entry', key: entry.key })} />)}
    </SheetFrame> : null}
    {activeEntry ? <SheetFrame title={activeEntry.title} labels={labels} palette={palette}
      onBack={() => setMenu({ kind: 'filters' })} onClose={() => setMenu(null)}>
      {[{ value: '', label: activeEntry.any }, ...activeEntry.options].map(option => <MenuRow key={option.value || 'any'}
        label={option.label} palette={palette}
        selected={String(activeEntry.value && activeEntry.value !== 'all' ? activeEntry.value : '') === String(option.value || '')}
        onPress={() => chooseEntry(activeEntry, option.value)} />)}
    </SheetFrame> : null}
    {menu?.kind === 'sort' ? <SheetFrame title={labels.sort} labels={labels} palette={palette} onClose={() => setMenu(null)}>
      {(options.sorts || []).map(sort => <MenuRow key={sort.value} label={sort.label} palette={palette}
        value={sort.value === (filters.sort || 'collected_at') ? ((filters.direction || 'desc') === 'asc' ? labels.ascending : labels.descending) : ''}
        selected={sort.value === (filters.sort || 'collected_at')}
        onPress={() => chooseSort(sort.value)} />)}
      {options.groupByMediaType ? <MenuRow label="Group by media type" checkbox
        selected={!!filters.groupByMediaType} disabled={view === 'table' || (filters.type && filters.type !== 'all')}
        palette={palette} onPress={() => { setMenu(null); onFilterChange?.({ type: 'set', key: 'groupByMediaType', value: !filters.groupByMediaType }); }} /> : null}
    </SheetFrame> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, minHeight: 44 },
  searchGlyph: { fontSize: 20 },
  searchInput: { flex: 1, fontSize: 14, paddingVertical: 8 },
  searchClear: { fontSize: 22, paddingHorizontal: 4 },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  toolButton: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 10, borderRadius: 8 },
  sortButton: { flexShrink: 1, minWidth: 0 },
  toolText: { fontSize: 14, flexShrink: 1 },
  viewToggle: { flexDirection: 'row', marginLeft: 'auto', borderWidth: 1, borderRadius: 8, overflow: 'hidden' },
  viewButton: { width: 44, height: 40, alignItems: 'center', justifyContent: 'center' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  gridItem: { width: 164 },
  rows: { gap: 18 },
  rowGroup: { gap: 8 },
  rowHeadingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  rowHeading: { fontSize: 14, fontWeight: '700' },
  rowScroll: { flexDirection: 'row', gap: 12, paddingBottom: 4 },
  rowCard: { width: 164 },
  table: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  tableHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1 },
  tableHeaderText: { flex: 1, fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  tableTitleHead: { flex: 1.6 },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 10, borderTopWidth: 1 },
  tableTitleCell: { flex: 1.6, minWidth: 0, gap: 4 },
  tableTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tableTitleBody: { flex: 1, minWidth: 0, gap: 4 },
  tableArtwork: { width: 40, height: 56, borderRadius: 4 },
  tableTitle: { fontSize: 13, fontWeight: '600' },
  tableCell: { flex: 1, fontSize: 12 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  empty: { borderWidth: 1, borderRadius: 10, padding: 24, gap: 6, alignItems: 'center' },
  emptyTitle: { fontSize: 16, fontWeight: '700' },
  emptyHint: { fontSize: 13, textAlign: 'center' },
  loadMore: { alignItems: 'center', paddingVertical: 14 },
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 },
  sheet: { width: '100%', maxWidth: 380, maxHeight: '70%', borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: 1 },
  sheetTitle: { flex: 1, fontSize: 12, fontWeight: '600', letterSpacing: 0.6, textTransform: 'uppercase' },
  close: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  closeText: { fontSize: 22 },
  menuList: { maxHeight: 360 },
  menuContent: { paddingBottom: 8 },
  menuRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, paddingVertical: 11 },
  menuText: { fontSize: 14, flex: 1 },
  menuValue: { fontSize: 12, maxWidth: 140 },
  check: { fontSize: 14, fontWeight: '700' },
});
