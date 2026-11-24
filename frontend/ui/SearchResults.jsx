import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { HomeShelves } from './HomeShelves';
import { Spinner } from './Spinner';
import { mergeSearchRowPage, useStreamedRows } from './searchRows';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  link: '#818cf8',
  danger: '#ef4444',
  radius: 8,
};

const defaultLabels = {
  title: 'Search results',
  emptyTitle: 'No results found',
  emptyBody: 'Try checking your spelling or using different keywords.',
  loading: 'Loading results…',
  searchingOnline: 'Searching online…',
  unavailable: 'is currently unavailable. Please try again shortly.',
  errorTitle: 'Search could not load',
  errorBody: 'Please try again.',
  retry: 'Try again',
};

// One row opened from its title: every loaded card in the shared card renderer, wrapped
// at the shelf card width, with the row's own paging behind "Load more".
function RowGrid({ row, renderCard, itemWidth, onLoadMore, palette, labels }) {
  const [current, setCurrent] = useState(row);
  const [loading, setLoading] = useState(false);
  useEffect(() => setCurrent(row), [row]);
  const items = current.items || [];
  const canLoadMore = Boolean(onLoadMore) && (current.loadedCount ?? items.length) < (current.total ?? 0);
  async function loadMore() {
    if (loading) return;
    setLoading(true);
    try {
      const next = await onLoadMore(current);
      if (next) setCurrent(next);
    } catch {
      // The button stays, so a failed page can be retried.
    } finally {
      setLoading(false);
    }
  }
  return <View style={styles.grid}>
    <View style={styles.gridCards}>
      {items.map(item => <View key={item.id} style={{ width: itemWidth }}>{renderCard(item, current)}</View>)}
    </View>
    {canLoadMore ? <Pressable accessibilityRole="button" onPress={loadMore} disabled={loading}
      style={[styles.retry, styles.loadMore, { backgroundColor: palette.surfaceStrong || palette.surface }]}>
      {loading ? <Spinner size={16} color={palette.accent} />
        : <Text style={[styles.retryText, { color: palette.text }]}>{labels.loadMore || 'Load more'}</Text>}
    </Pressable> : null}
  </View>;
}

function EmptyState({ empty, palette, labels }) {
  return <View style={[styles.empty, { backgroundColor: palette.surface }]}>
    <Text role="heading" aria-level={2} style={[styles.emptyTitle, { color: palette.text }]}>
      {empty?.title || labels.emptyTitle}
    </Text>
    <Text style={[styles.emptyBody, { color: palette.textMuted }]}>{empty?.body || labels.emptyBody}</Text>
    {empty?.extra ? <Text style={[styles.emptyBody, { color: palette.textMuted }]}>{empty.extra}</Text> : null}
  </View>;
}

/**
 * Search results as Home's shelves: your library first, then one row per provider
 * that has something. The rows arrive in the shape Home's rows have, so the same
 * rail, card, card size and load-more drive both pages. Web and native supply the
 * card renderer, the width and the handlers, exactly as they do for Home.
 */
export function SearchResults({
  title,
  state = 'ready',
  labels = {},
  palette: paletteOverrides,
  notes = [],
  rows: baseRows = [],
  onlineSources = [],
  onLoadOnlineRow,
  focusRowId,
  onFocusRow,
  railComponent,
  empty,
  itemWidth,
  renderCard,
  renderRating,
  renderActionIcon,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  onLoadMore,
  onRetry,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, ...labels };
  const { width } = useWindowDimensions();
  // The same heading size as a Home row's title.
  const compact = width < 640;
  // A focused row asks only its own provider, so a grid opened from a title costs one request.
  const focused = Boolean(focusRowId);
  const { rows: streamed, failed, pending } = useStreamedRows({
    rows: baseRows,
    onlineSources: focused ? onlineSources.filter(source => source.rowId === focusRowId) : onlineSources,
    loadOnlineRow: onLoadOnlineRow, resetKey: String(testID || ''),
  });
  const focusRow = focused ? streamed.find(row => String(row.rowId) === String(focusRowId)) : null;
  const rows = focused ? (focusRow ? [focusRow] : []) : streamed;
  // A title opens that row as a grid. HomeShelves makes a title a link when the row has a
  // `url`, so the row's id stands in as the url and `onOpenRowTitle` turns it into the grid.
  const shelfRows = onFocusRow && !focused ? rows.map(row => ({ ...row, url: row.url || String(row.rowId) })) : rows;
  const groups = shelfRows.length ? [{ mediaType: 'search', label: '', rows: shelfRows }] : [];
  return <View style={styles.wrapper} testID={testID}>
    {failed.map(label => <Text key={label} style={[styles.note, { color: palette.textMuted }]}>{`${label} ${copy.unavailable}`}</Text>)}
    {notes.map((note, index) => <Text key={index} style={[styles.note, { color: palette.textMuted }]}>{note}</Text>)}
    {state === 'loading' ? <View style={styles.state}>
      <Spinner size={20} color={palette.accent} />
      <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.loading}</Text>
    </View> : null}
    {state === 'error' ? <View style={styles.state}>
      <Text role="heading" aria-level={2} style={[styles.stateTitle, { color: palette.text }]}>{copy.errorTitle}</Text>
      <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.errorBody}</Text>
      <Pressable accessibilityRole="button" onPress={onRetry}
        style={[styles.retry, { backgroundColor: palette.accentStrong || palette.accent }]}>
        <Text style={[styles.retryText, { color: palette.accentText }]}>{copy.retry}</Text>
      </Pressable>
    </View> : null}
    {state === 'empty' || (state === 'ready' && !rows.length && !pending)
      ? <EmptyState empty={empty} palette={palette} labels={copy} /> : null}
    {state === 'ready' && focusRow ? <View style={styles.wrapper}>
      <Pressable accessibilityRole="link" onPress={() => onFocusRow?.(null)}>
        <Text style={[styles.back, { color: palette.link }]}>{`‹ ${copy.title}`}</Text>
      </Pressable>
      <Text role="heading" aria-level={2} style={[styles.title, compact && styles.titleCompact, { color: palette.text }]}>
        {focusRow.titleDetail ? `${focusRow.titleMain || focusRow.title} • ${focusRow.titleDetail}` : (focusRow.titleMain || focusRow.title)}
      </Text>
      <RowGrid row={focusRow} renderCard={renderCard} itemWidth={itemWidth} onLoadMore={onLoadMore}
        palette={palette} labels={{ ...copy, ...labels }} />
    </View> : null}
    {state === 'ready' && !focused && rows.length ? <HomeShelves
      railComponent={railComponent}
      groups={groups}
      labels={labels}
      palette={palette}
      itemWidth={itemWidth}
      renderCard={renderCard}
      renderRating={renderRating}
      renderActionIcon={renderActionIcon}
      onOpenCard={onOpenCard}
      onOpenLink={onOpenLink}
      onOpenRowTitle={onFocusRow ? (_url, row) => onFocusRow(row) : undefined}
      onAction={onAction}
      onRate={onRate}
      onLoadMore={onLoadMore} /> : null}
    {state === 'ready' && pending ? <View style={styles.searching}>
      <Spinner size={16} color={palette.accent} />
      <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.searchingOnline}</Text>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { gap: 16, minWidth: 0 },
  title: { fontSize: 18, fontWeight: '600', lineHeight: 18 },
  titleCompact: { fontSize: 16, lineHeight: 21.6 },
  back: { fontSize: 14, lineHeight: 20 },
  grid: { gap: 16, minWidth: 0 },
  gridCards: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  loadMore: { alignSelf: 'center', minWidth: 140, alignItems: 'center' },
  note: { fontSize: 14, lineHeight: 20 },
  searching: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 },
  state: { alignItems: 'center', justifyContent: 'center', gap: 12, paddingVertical: 48 },
  stateTitle: { fontSize: 18, fontWeight: '600' },
  stateText: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  retry: { borderRadius: 8, paddingHorizontal: 16, paddingVertical: 10 },
  retryText: { fontSize: 14, fontWeight: '600' },
  empty: { borderRadius: 12, alignItems: 'center', gap: 8, paddingVertical: 40, paddingHorizontal: 24 },
  emptyTitle: { fontSize: 18, fontWeight: '600', textAlign: 'center' },
  emptyBody: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
});
