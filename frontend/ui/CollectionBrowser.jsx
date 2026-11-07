import React, { useMemo, useState } from 'react';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { FilterBar } from './FilterBar';
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
  allTypes: 'All types',
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
  ratingUnrated: 'Not rated',
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

function FilterMenu({ menu, labels, palette, onChoose, onClose }) {
  if (!menu) return null;
  const colors = palette;
  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.close}
        style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={[styles.sheet, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.sheetHeader}>
          <Text style={[styles.sheetTitle, { color: colors.text }]}>{menu.title}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={labels.close} onPress={onClose}
            style={styles.close}>
            <Text style={[styles.closeText, { color: colors.textMuted }]}>×</Text>
          </Pressable>
        </View>
        <ScrollView style={styles.menuList} contentContainerStyle={styles.menuContent}>
          {[{ value: '', label: labels.any }, ...(menu.options || [])].map(option => {
            const selected = String(menu.value || '') === String(option.value || '');
            return <Pressable key={`${menu.key}-${option.value || 'any'}`}
              accessibilityRole="radio" accessibilityLabel={option.label}
              accessibilityState={{ checked: selected }}
              onPress={() => onChoose(menu.key, option.value)}
              style={({ pressed }) => [styles.menuRow, {
                backgroundColor: selected ? colors.accent : pressed ? colors.surfaceStrong : 'transparent',
              }]}>
              <Text style={[styles.menuText, { color: selected ? colors.accentContrast : colors.textSecondary }]}>
                {option.label}
              </Text>
              {selected ? <Text style={[styles.check, { color: colors.accentContrast }]}>✓</Text> : null}
            </Pressable>;
          })}
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

const DEFAULT_TABLE_COLUMNS = ['title', 'type', 'format', 'resolution', 'collected'];

function tableColumnLabel(column, labels) {
  return labels[column] || column;
}

function tableCellValue(item, column, labels) {
  if (column === 'type') return item.mediaTypeLabel || item.mediaType || '—';
  if (column === 'format') return item.format || '—';
  if (column === 'resolution') return item.resolution || '—';
  if (column === 'collected') return item.collectedAt || '—';
  if (column === 'hdr') return item.hdr || '—';
  if (column === 'location') return item.purchaseLocation || '—';
  return item[column] == null ? '—' : String(item[column]);
}

function TableView({ items, labels, palette, columns, onOpenCopy }) {
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
        accessibilityLabel={`${item.title} ${labels.editCopies}`}
        onPress={() => onOpenCopy?.(item)}
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

function GridView({ items, labels, palette, onOpenCopy, renderCard }) {
  return <View style={styles.grid}>
    {items.map(item => <View key={item.id} style={styles.gridItem}>
      {renderCard ? renderCard(item) : <MediaCard model={cardModel(item)} width={164} palette={{
        ...palette,
        card: palette.surface,
        link: '#818cf8',
        star: '#facc15',
      }} labels={labels} onOpen={() => onOpenCopy?.(item)} />}
    </View>)}
  </View>;
}

function RowView({ items, groups, labels, palette, onOpenCopy, onLoadMoreGroup, renderCard }) {
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
            }} labels={labels} onOpen={() => onOpenCopy?.(item)} />}
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
  onLoadMore,
  onLoadMoreGroup,
  renderCard,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  const [menu, setMenu] = useState(null);
  const activeCount = filterCount(filters);
  const view = filters.view || 'grid';

  const barFilters = {
    mediaTypes: filters.type && filters.type !== 'all' ? [filters.type] : [],
    statuses: filters.completeness && filters.completeness !== 'all' ? [filters.completeness] : [],
    sort: filters.sort || 'collected_at',
    direction: filters.direction || 'desc',
    view,
    ranges: {},
  };
  const barOptions = {
    mediaTypes: options.mediaTypes || [],
    statuses: [
      { value: 'partial', label: labels.partial },
      { value: 'full', label: labels.full },
    ],
    sorts: options.sorts || [],
    views: [
      { value: 'grid', label: labels.grid },
      { value: 'rows', label: labels.rows },
      { value: 'table', label: labels.table },
    ],
    savedViews: [],
    ranges: [],
  };

  const secondary = [
    options.formats?.length ? { key: 'format', title: labels.formatFilter, value: filters.format, options: options.formats } : null,
    options.resolutions?.length ? { key: 'resolution', title: labels.resolutionFilter, value: filters.resolution, options: options.resolutions } : null,
    options.hdrs?.length ? { key: 'hdr', title: labels.hdr, value: filters.hdr, options: options.hdrs } : null,
    options.locations?.length ? { key: 'location', title: labels.location, value: filters.location, options: options.locations } : null,
    {
      key: 'rating',
      title: labels.rating,
      value: filters.rating,
      options: [
        { value: 'rated', label: labels.ratingRated },
        { value: 'not_rated', label: labels.ratingUnrated },
      ],
    },
    options.customFilter ? {
      key: 'custom',
      title: options.customFilter.label || labels.customField,
      value: filters.customValue,
      options: options.customFilter.choices || [],
    } : null,
  ].filter(Boolean);

  function handleFilterIntent(intent) {
    if (intent.type === 'clear') {
      onFilterChange?.({ type: 'reset' });
      return;
    }
    if (intent.type === 'toggle' && intent.key === 'mediaTypes') {
      onFilterChange?.({ type: 'type', value: filters.type === intent.value ? 'all' : intent.value });
      return;
    }
    if (intent.type === 'toggle' && intent.key === 'statuses') {
      onFilterChange?.({
        type: 'completeness',
        value: filters.completeness === intent.value ? 'all' : intent.value,
      });
      return;
    }
    if (intent.type === 'set' && intent.key === 'mediaTypes') {
      onFilterChange?.({ type: 'type', value: intent.value });
      return;
    }
    if (intent.type === 'set' && intent.key === 'statuses') {
      onFilterChange?.({ type: 'completeness', value: intent.value });
      return;
    }
    if (intent.type === 'set') {
      onFilterChange?.(intent);
    }
  }

  function chooseSecondary(key, value) {
    setMenu(null);
    if (key === 'custom') {
      onFilterChange?.({ type: 'set', key: 'customFilter', value: options.customFilter?.id || '' });
      onFilterChange?.({ type: 'set', key: 'customValue', value });
      return;
    }
    onFilterChange?.({ type: 'set', key, value: value || 'all' });
  }

  return <View style={styles.root}>
    {chrome ? <View style={[styles.searchRow, { borderColor: palette.border, backgroundColor: palette.surface }]}>
      <Text style={[styles.searchGlyph, { color: palette.textMuted }]}>⌕</Text>
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

    {chrome ? <FilterBar filters={barFilters} options={barOptions} labels={{
      filters: labels.filters,
      allTypes: labels.allTypes,
      mediaType: labels.type,
      status: labels.status,
      allStatuses: labels.allStatuses,
      sort: labels.sort,
      view: labels.view,
      clear: labels.clear,
      clearAll: labels.clearAll,
      items: labels.results,
      ascending: 'ascending',
      descending: 'descending',
      updating: 'Updating results',
    }} palette={{
      ...palette,
      surfaceHover: palette.surfaceMuted,
      accentText: palette.accentContrast,
      disabled: palette.textMuted,
    }} busy={busy} resultCount={typeof resultCount === 'number' ? resultCount : items.length}
      onChange={handleFilterIntent} /> : null}

    {chrome && secondary.length ? <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.chipRow}>
      {secondary.map(entry => {
        const selected = entry.value && entry.value !== 'all'
          ? (entry.options.find(option => String(option.value) === String(entry.value))?.label || entry.value)
          : null;
        return <Pressable key={entry.key} accessibilityRole="button"
          accessibilityLabel={`${entry.title}: ${selected || labels.any}`}
          onPress={() => setMenu({
            key: entry.key,
            title: entry.title,
            value: entry.key === 'custom' ? filters.customValue : entry.value,
            options: entry.options,
          })}
          style={({ pressed }) => [styles.filterChip, {
            backgroundColor: selected ? `${palette.accent}33` : palette.surface,
            borderColor: selected ? palette.accent : palette.border,
            opacity: pressed ? 0.75 : 1,
          }]}>
          <Text style={[styles.filterChipText, { color: selected ? palette.text : palette.textSecondary }]}>
            {entry.title}{selected ? ` · ${selected}` : ''}
          </Text>
        </Pressable>;
      })}
      {activeCount ? <Pressable accessibilityRole="button" accessibilityLabel={labels.clearAll}
        onPress={() => onFilterChange?.({ type: 'reset' })}
        style={({ pressed }) => [styles.filterChip, {
          backgroundColor: 'transparent', borderColor: palette.border, opacity: pressed ? 0.6 : 1,
        }]}>
        <Text style={[styles.filterChipText, { color: palette.accent }]}>{labels.clear}</Text>
      </Pressable> : null}
    </ScrollView> : null}

    {items.length === 0 && !groups?.length ? <View style={[styles.empty, { borderColor: palette.border, backgroundColor: palette.surface }]}>
      <Text style={[styles.emptyTitle, { color: palette.text }]}>{labels.empty}</Text>
      <Text style={[styles.emptyHint, { color: palette.textMuted }]}>{labels.emptyHint}</Text>
    </View> : view === 'table'
      ? <TableView items={items} labels={labels} palette={palette} columns={tableColumns} onOpenCopy={onOpenCopy} />
      : view === 'rows'
        ? <RowView items={items} groups={groups} labels={labels} palette={palette}
          onOpenCopy={onOpenCopy} onLoadMoreGroup={onLoadMoreGroup} renderCard={renderCard} />
        : <GridView items={items} labels={labels} palette={palette} onOpenCopy={onOpenCopy} renderCard={renderCard} />}

    {!groups?.length && (hasMore || loadingMore) ? <View style={styles.loadMore} testID="collection-load-more">
      <Button label={labels.loadMore} tone="surface" palette={palette}
        busy={loadingMore} disabled={loadingMore} onPress={onLoadMore} />
    </View> : null}

    <FilterMenu menu={menu} labels={labels} palette={palette}
      onChoose={chooseSecondary} onClose={() => setMenu(null)} />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, minHeight: 44 },
  searchGlyph: { fontSize: 20 },
  searchInput: { flex: 1, fontSize: 14, paddingVertical: 8 },
  searchClear: { fontSize: 22, paddingHorizontal: 4 },
  chipRow: { flexDirection: 'row', gap: 8, paddingVertical: 2 },
  filterChip: { borderWidth: 1, borderRadius: 9999, paddingHorizontal: 12, paddingVertical: 7 },
  filterChipText: { fontSize: 12, fontWeight: '600' },
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
  sheetHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, paddingVertical: 10 },
  sheetTitle: { fontSize: 15, fontWeight: '700' },
  close: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  closeText: { fontSize: 22 },
  menuList: { maxHeight: 360 },
  menuContent: { paddingBottom: 8 },
  menuRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, paddingVertical: 11 },
  menuText: { fontSize: 13 },
  check: { fontSize: 14, fontWeight: '700' },
});
