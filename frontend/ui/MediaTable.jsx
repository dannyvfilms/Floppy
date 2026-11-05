import React, { useEffect, useMemo, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

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
  accentContrast: '#ffffff',
  link: '#818cf8',
  warning: '#f59e0b',
  success: '#10b981',
  danger: '#ef4444',
};

const FALLBACK_LABELS = {
  empty: 'No items match these filters.',
  showMore: 'Show more rows',
  showingBounded: 'Showing the first {count} rows',
  selectItem: 'Select',
  columns: 'Columns',
};

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...FALLBACK_LABELS, ...(labels || {}) };
}

function columnWidth(column) {
  if (column.width) {
    return column.width;
  }
  if (column.key === 'image') {
    return 56;
  }
  if (column.key === 'title' || column.primary) {
    return 260;
  }
  return 128;
}

function cellText(cell) {
  if (!cell) {
    return '—';
  }
  if (cell.text != null) {
    return String(cell.text);
  }
  return '—';
}

function isSelected(selectedIds, id) {
  if (!selectedIds) {
    return false;
  }
  return typeof selectedIds.has === 'function'
    ? selectedIds.has(id)
    : selectedIds.includes(id);
}

function Note({ text, color }) {
  if (!text) {
    return null;
  }
  return <Text style={[styles.cellNote, { color }]}>{text}</Text>;
}

export function MediaTableCell({
  cell,
  column,
  palette,
  labels,
  onOpenLink,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const type = cell?.kind || 'text';
  const note = cell?.note || '';
  const noteColor = type === 'score' ? colors.link : colors.textMuted;

  if (type === 'image') {
    const initials = (cell?.alt || '').trim().slice(0, 1).toUpperCase();
    return <View style={styles.imageCell}>
      {cell?.src
        ? <Image source={{ uri: cell.src }} accessibilityLabel={cell.alt || ''}
            style={[styles.image, { backgroundColor: colors.surfaceStrong }]} />
        : <View style={[styles.image, styles.imageFallback, { backgroundColor: colors.surfaceStrong }]}>
            <Text style={[styles.imageInitial, { color: colors.textMuted }]}>{initials || '·'}</Text>
          </View>}
    </View>;
  }

  if (type === 'tags' || type === 'genres') {
    const tags = cell?.items || [];
    if (!tags.length) {
      return <Text style={[styles.cellText, { color: colors.textMuted }]}>—</Text>;
    }
    return <View style={styles.tagList}>
      {tags.map((tag, index) => <Pressable key={`${tag.label}-${index}`}
        accessibilityRole={tag.href ? 'link' : undefined}
        accessibilityLabel={tag.label}
        disabled={!tag.href}
        onPress={tag.href ? event => {
          event?.stopPropagation?.();
          onOpenLink?.(tag.href);
        } : undefined}
        style={[styles.tag, { backgroundColor: colors.surfaceStrong }]}>
        <Text style={[styles.tagText, { color: tag.href ? colors.link : colors.textSecondary }]}>
          {tag.label}
        </Text>
      </Pressable>)}
    </View>;
  }

  if (type === 'link' || type === 'title') {
    const text = cellText(cell);
    const content = <Text numberOfLines={1}
      style={[type === 'title' ? styles.titleText : styles.cellText, {
        color: type === 'title' ? colors.text : colors.link,
      }]}>
      {text}
    </Text>;
    return <View style={styles.titleCell}>
      {cell?.href
        ? <Pressable accessibilityRole="link" accessibilityLabel={text}
            onPress={event => {
              event?.stopPropagation?.();
              onOpenLink?.(cell.href);
            }} style={styles.linkPress}>
            {content}
          </Pressable>
        : content}
      {cell?.repeats > 1 ? <View style={styles.repeatBadge}>
        <Text style={[styles.repeatText, { color: colors.textSecondary }]}>↻ {cell.repeats}</Text>
      </View> : null}
      <Note text={note} color={noteColor} />
    </View>;
  }

  if (type === 'score') {
    const rated = !!cell?.rated;
    return <View style={styles.centerCell}>
      <View style={styles.scoreRow}>
        <Text style={[styles.star, { color: rated ? colors.warning : colors.textMuted }]}>★</Text>
        {rated ? <Text style={[styles.scoreText, { color: colors.text }]}>{cellText(cell)}</Text> : null}
      </View>
      <Note text={note} color={noteColor} />
    </View>;
  }

  if (type === 'status') {
    return <View style={styles.centerCell}>
      <Text style={[styles.statusText, { color: cell?.muted ? colors.textMuted : colors.textSecondary }]}>
        {cellText(cell)}
      </Text>
      <Note text={note} color={noteColor} />
    </View>;
  }

  if (type === 'progress') {
    return <View style={styles.centerCell}>
      <Text style={[styles.progressText, { color: colors.text }]}>
        {cellText(cell)}{cell?.maxText ? <Text style={{ color: colors.textMuted }}>{cell.maxText}</Text> : null}
      </Text>
      <Note text={note} color={noteColor} />
    </View>;
  }

  return <View style={[styles.cell, column.align === 'center' && styles.centerCell]}>
    <Text numberOfLines={column.limitLines || 1}
      style={[styles.cellText, { color: cell?.muted ? colors.textMuted : colors.textSecondary }]}>
      {cellText(cell)}
    </Text>
    <Note text={note} color={noteColor} />
  </View>;
}

export function MediaTable({
  columns = [],
  rows = [],
  sort,
  sortDirection = 'desc',
  onSort,
  onOpen,
  onOpenLink,
  palette,
  labels,
  selectMode = false,
  selectedIds,
  onToggleItem,
  rowLimit = 50,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  caption,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [limit, setLimit] = useState(rowLimit);
  useEffect(() => {
    setLimit(rowLimit);
  }, [rowLimit]);
  const shown = useMemo(() => rows.slice(0, Math.max(limit, 1)), [rows, limit]);
  const bounded = shown.length < rows.length;
  const totalWidth = selectMode ? 28 : 0;
  const tableWidth = columns.reduce((sum, column) => sum + columnWidth(column), totalWidth);

  if (!rows.length) {
    return <View style={[styles.empty, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <Text style={[styles.emptyText, { color: colors.textMuted }]}>{copy.empty}</Text>
    </View>;
  }

  return <View style={styles.tableRoot}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ minWidth: tableWidth }}>
      <View accessibilityRole="table" accessibilityLabel={caption || copy.columns}
        style={[styles.table, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <View accessibilityRole="row" style={[styles.row, styles.headerRow, { borderColor: colors.border }]}>
          {selectMode ? <View style={styles.checkColumn} /> : null}
          {columns.map(column => {
            const active = sort === column.key;
            const label = column.label || '';
            return <View key={column.key} accessibilityRole="columnheader"
              accessibilityLabel={label}
              style={[styles.cell, styles.headerCell, {
                width: columnWidth(column),
                alignItems: column.align === 'center' ? 'center' : 'flex-start',
              }]}>
              {onSort && column.sortable !== false && label
                ? <Pressable accessibilityRole="button" accessibilityLabel={label}
                    accessibilityState={{ selected: active }}
                    onPress={() => onSort(column.key)}
                    style={styles.sortPress}>
                    <Text style={[styles.headerText, { color: active ? colors.accent : colors.textMuted }]}>
                      {label}{active ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : ''}
                    </Text>
                  </Pressable>
                : <Text style={[styles.headerText, { color: colors.textMuted }]}>{label}</Text>}
            </View>;
          })}
        </View>
        {shown.map((row, rowIndex) => {
          const rowId = row.id ?? rowIndex;
          const rowContent = <>
            {selectMode ? <Pressable accessibilityRole="checkbox"
              accessibilityLabel={`${copy.selectItem} ${row.title || ''}`}
              accessibilityState={{ checked: isSelected(selectedIds, rowId) }}
              onPress={event => {
                event?.stopPropagation?.();
                onToggleItem?.(rowId);
              }}
              style={styles.checkColumn}>
              <Text style={[styles.checkText, { color: isSelected(selectedIds, rowId) ? colors.accent : colors.textMuted }]}>
                {isSelected(selectedIds, rowId) ? '✓' : '○'}
              </Text>
            </Pressable> : null}
            {columns.map(column => <View key={column.key} style={[styles.cell, {
              width: columnWidth(column),
            }]}>
              <MediaTableCell cell={row.cells?.[column.key]} column={column}
                palette={colors} labels={copy} onOpenLink={onOpenLink} />
            </View>)}
          </>;
          if (!onOpen) {
            return <View key={rowId} accessibilityRole="row"
              style={[styles.row, { borderColor: colors.border }]}>{rowContent}</View>;
          }
          return <Pressable key={rowId} accessibilityRole="button"
            accessibilityLabel={row.title || ''}
            onPress={() => onOpen(row)}
            style={({ pressed }) => [styles.row, {
              borderColor: colors.border,
              backgroundColor: pressed ? colors.surfaceStrong : 'transparent',
            }]}>{rowContent}</Pressable>;
        })}
      </View>
    </ScrollView>
    {bounded ? <Pressable accessibilityRole="button" accessibilityLabel={copy.showMore}
      onPress={() => setLimit(current => current + rowLimit)}
      style={[styles.showMore, { backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.showMoreText, { color: colors.link }]}>
        {copy.showMore} ({rows.length - shown.length})
      </Text>
    </Pressable> : null}
    {hasMore && onLoadMore ? <Pressable accessibilityRole="button"
      accessibilityLabel={loadingMore ? 'Loading more rows' : copy.showMore}
      disabled={loadingMore} onPress={onLoadMore}
      style={[styles.showMore, { backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.showMoreText, { color: loadingMore ? colors.textMuted : colors.link }]}>
        {loadingMore ? 'Loading…' : copy.showMore}
      </Text>
    </Pressable> : null}
    {rows.length >= rowLimit ? <Text style={[styles.limitNote, { color: colors.textMuted }]}>
      {copy.showingBounded.replace('{count}', String(shown.length))}
    </Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  tableRoot: { gap: 8 },
  table: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1, paddingHorizontal: 4, minHeight: 48 },
  headerRow: { borderTopWidth: 0, minHeight: 38 },
  headerCell: { justifyContent: 'center' },
  headerText: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  sortPress: { paddingVertical: 4 },
  cell: { paddingHorizontal: 8, paddingVertical: 6, justifyContent: 'center' },
  centerCell: { alignItems: 'center', justifyContent: 'center' },
  cellText: { fontSize: 13 },
  titleText: { fontSize: 13, fontWeight: '600' },
  titleCell: { gap: 2 },
  linkPress: { paddingVertical: 2 },
  cellNote: { fontSize: 10, marginTop: 2 },
  imageCell: { alignItems: 'center', justifyContent: 'center' },
  image: { width: 40, height: 40, borderRadius: 6 },
  imageFallback: { alignItems: 'center', justifyContent: 'center' },
  imageInitial: { fontSize: 16, fontWeight: '700' },
  tagList: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  tag: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  tagText: { fontSize: 11, fontWeight: '600' },
  scoreRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  star: { fontSize: 13 },
  scoreText: { fontSize: 13, fontWeight: '600' },
  statusText: { fontSize: 13 },
  progressText: { fontSize: 13, fontWeight: '600' },
  repeatBadge: { alignSelf: 'flex-start' },
  repeatText: { fontSize: 10, fontWeight: '600' },
  checkColumn: { width: 28, alignItems: 'center', justifyContent: 'center' },
  checkText: { fontSize: 16, fontWeight: '700' },
  empty: { borderWidth: 1, borderRadius: 10, padding: 32, alignItems: 'center' },
  emptyText: { fontSize: 13 },
  showMore: { alignSelf: 'center', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  showMoreText: { fontSize: 12, fontWeight: '600' },
  limitNote: { fontSize: 11, textAlign: 'center' },
});
