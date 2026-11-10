import React from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { HomeShelves } from './HomeShelves';
import { Spinner } from './Spinner';
import { useStreamedRows } from './searchRows';

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
  const { rows, failed, pending } = useStreamedRows({
    rows: baseRows, onlineSources, loadOnlineRow: onLoadOnlineRow, resetKey: String(testID || ''),
  });
  const groups = rows.length ? [{ mediaType: 'search', label: '', rows }] : [];
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
    {state === 'ready' && rows.length ? <HomeShelves
      groups={groups}
      labels={labels}
      palette={palette}
      itemWidth={itemWidth}
      renderCard={renderCard}
      renderRating={renderRating}
      renderActionIcon={renderActionIcon}
      onOpenCard={onOpenCard}
      onOpenLink={onOpenLink}
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
