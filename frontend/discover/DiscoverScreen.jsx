import React, { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { actionIcons } from '../ui/actionIcons';
import { Badge } from '../ui/Badge';
import { Icon } from '../ui/Icon';
import { MediaCard } from '../ui/MediaCard';
import { RefreshNotice } from '../ui/RefreshNotice';
import { Rail } from '../ui/Rail';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  accentText: '#ffffff',
  warning: '#f59e0b',
  success: '#10b981',
  danger: '#ef4444',
  radius: 8,
};

export const defaultLabels = {
  mediaType: 'Media type',
  showMore: 'Show More Rows',
  showFewer: 'Show Fewer Rows',
  refresh: 'Refresh recommendations',
  refreshing: 'Refreshing…',
  refreshBackground: 'Refreshing recommendations in background...',
  refreshDone: 'Recommendations refreshed.',
  undo: 'Undo',
  dismiss: 'Dismiss',
  hiddenTitle: 'Hidden From Discover',
  hiddenBody: 'Most recently changed first, so forgotten hides are easy to find again.',
  hiddenItem: 'item',
  hiddenItems: 'items',
  hiddenEmptyTitle: 'Nothing hidden right now',
  hiddenEmptyBody: 'Items you hide from Discover will show up here.',
  emptyTitle: 'No Discover rows available',
  emptyBody: 'Try another media type or start tracking more items.',
  loadingTitle: 'Building Discover rows',
  loadingBody: 'Recommendations are refreshing in the background and will appear automatically.',
  rowEmptyContinue: 'Nothing to continue yet. Track something as in progress and it will appear here.',
  rowEmptyDefault: 'No items matched this row right now.',
  previewEmpty: 'No items matched this row right now.',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
};

function resolvePalette(palette) {
  return { ...defaultPalette, ...(palette || {}) };
}

function copyFor(labels) {
  return { ...defaultLabels, ...(labels || {}) };
}

function countLabel(copy, count) {
  return `${count} ${count === 1 ? copy.hiddenItem : copy.hiddenItems}`;
}



export function DiscoverTabs({
  items = [],
  selected,
  onSelect,
  label,
  labels,
  palette: paletteOverrides,
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  return <View style={styles.tabs}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.tabRow}>
      {items.map(item => {
        const active = selected === item.value;
        return <Pressable key={item.value} accessibilityRole="link"
          accessibilityLabel={item.label} accessibilityState={{ selected: active }}
          onPress={() => onSelect?.(item.value)}
          style={[styles.tab, {
            backgroundColor: active ? palette.accent : palette.surface,
            borderColor: active ? palette.accent : palette.border,
          }]}>
          <Text style={[styles.tabText, { color: active ? palette.accentText : palette.textSecondary }]}>{item.label}</Text>
        </Pressable>;
      })}
    </ScrollView>
    <Text style={styles.srOnly} accessibilityLiveRegion="polite">
      {selected ? `${copy.mediaType}: ${(items.find(item => item.value === selected) || {}).label || selected}` : ''}
    </Text>
  </View>;
}

export function DiscoverFeedback({
  refreshing = false,
  cacheRefreshing = false,
  refreshStatus,
  toast,
  labels,
  palette: paletteOverrides,
  toastStyle,
  onDismissRefreshStatus,
  onDismissToast,
  onUndo,
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const status = refreshStatus || {};
  const message = toast || {};
  const showToast = Boolean(message.visible && (message.message || message.undoToken));
  return <View style={styles.feedbackStack}>
    {cacheRefreshing ? <RefreshNotice state="loading" message={copy.refreshBackground}
      palette={palette} background="rgba(245, 158, 11, 0.12)"
      border="rgba(245, 158, 11, 0.3)" color={palette.warning} /> : null}
    {status.visible ? <RefreshNotice state="complete" message={status.message || copy.refreshDone}
      labels={{ dismiss: copy.dismiss }} palette={palette}
      background="rgba(16, 185, 129, 0.12)" border="rgba(16, 185, 129, 0.3)"
      color={palette.success} onDismiss={onDismissRefreshStatus} /> : null}
    {showToast ? <View accessibilityLiveRegion="polite"
      style={[styles.toast, { backgroundColor: palette.surface, borderColor: palette.border }, toastStyle]}>
      <Text style={[styles.toastText, { color: palette.text }]}>{message.message}</Text>
      {message.undoToken ? <Badge label={copy.undo} size="sm" onPress={onUndo}
        appearance={{ color: palette.accentText, backgroundColor: palette.accent, borderWidth: 0 }} /> : null}
      <Pressable accessibilityRole="button" accessibilityLabel={copy.dismiss}
        onPress={onDismissToast} style={styles.dismissButton}>
        <Icon spec={actionIcons.x} color={palette.textMuted} size={16} />
      </Pressable>
    </View> : null}
    {refreshing ? <Text style={styles.srOnly} accessibilityLiveRegion="polite">{copy.refreshing}</Text> : null}
  </View>;
}

export function DiscoverState({
  kind = 'empty',
  labels,
  palette: paletteOverrides,
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const title = kind === 'loading'
    ? copy.loadingTitle
    : kind === 'hidden-empty' ? copy.hiddenEmptyTitle : copy.emptyTitle;
  const body = kind === 'loading'
    ? copy.loadingBody
    : kind === 'hidden-empty' ? copy.hiddenEmptyBody : copy.emptyBody;
  const loading = kind === 'loading';
  return <View style={[styles.state, {
    backgroundColor: loading ? 'rgba(245, 158, 11, 0.12)' : palette.surface,
    borderColor: loading ? 'rgba(245, 158, 11, 0.3)' : palette.border,
  }]}>
    <Text role="heading" aria-level={2} style={[styles.stateTitle, { color: palette.text }]}>{title}</Text>
    <Text style={[styles.stateBody, { color: loading ? palette.warning : palette.textMuted }]}>{body}</Text>
  </View>;
}

function DiscoverCard({
  model,
  labels,
  palette,
  width,
  square = false,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  readOnly,
}) {
  return <MediaCard model={model} width={width} labels={labels} palette={palette}
    variant={square ? 'grid-square' : 'grid'}
    readOnly={readOnly}
    onOpen={() => onOpenCard?.(model.href, model)}
    onOpenLink={href => onOpenLink?.(href)}
    onAction={action => onAction?.(model, action)}
    onRate={onRate ? score => onRate(model, score) : undefined}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon} />;
}

const gridGap = 16;
const mobileGridGap = 12;
const mobileCardCap = 108;
const gridMinCardWidth = 180;
const compactColumns = 3;

export function mediaGridMetrics(width) {
  if (!width) return { columns: compactColumns, gap: gridGap, cardWidth: undefined };
  const gap = width <= 768 ? mobileGridGap : gridGap;
  if (width <= 600) {
    return {
      columns: compactColumns,
      gap,
      cardWidth: Math.min((width - gap * (compactColumns - 1)) / compactColumns, mobileCardCap),
    };
  }
  const columns = width >= 480
    ? Math.max(1, Math.floor((width + gap) / (gridMinCardWidth + gap)))
    : compactColumns;
  return { columns, gap, cardWidth: (width - gap * (columns - 1)) / columns };
}

export function DiscoverRow({
  row,
  labels,
  palette: paletteOverrides,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  readOnly = false,
  initialGridWidth = 0,
}) {
  const [gridWidth, setGridWidth] = useState(initialGridWidth || 0);
  const onGridLayout = useCallback(event => {
    const width = event?.nativeEvent?.layout?.width || 0;
    setGridWidth(current => (Math.abs(current - width) < 0.5 ? current : width));
  }, []);
  if (!row) return null;
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const emptyLabel = row.emptyLabel || (row.continueRow ? copy.rowEmptyContinue : copy.rowEmptyDefault);
  const items = row.items || [];
  const squareRow = items[0]?.mediaType === 'podcast' || items[0]?.mediaType === 'music';
  const { cardWidth, gap } = mediaGridMetrics(gridWidth);
  return <View nativeID={`discover-row-${row.key}`} style={styles.row}>
    <View style={styles.rowHeading}>
      <View style={styles.rowHeadingText}>
        <Text role="heading" aria-level={2} style={[styles.rowTitle, { color: palette.text }]}>{row.title}</Text>
        <View style={styles.rowMeta}>
          <Text style={[styles.rowWhy, { color: palette.textMuted }]}>{row.why}</Text>
          {row.matchSignal ? <Text style={[styles.rowSignal, { color: palette.textMuted }]}>{row.matchSignal}</Text> : null}
        </View>
      </View>
      {row.isStale ? <Text style={[styles.rowStale, { color: palette.warning }]}>{copy.refreshing}</Text> : null}
    </View>
    {items.length
      ? <View accessibilityRole="list"
        accessibilityLabel={`${row.title}${row.why ? ` • ${row.why}` : ''}`}
        onLayout={onGridLayout}
        style={[styles.rowGrid, { gap }]}>
        {items.map((item, index) => <View key={item?.cardKey || item?.id || index}
          style={[styles.rowGridItem, cardWidth ? { width: cardWidth } : null]}>
          <DiscoverCard model={squareRow ? { ...item, shape: 'square' } : item} width={cardWidth}
            square={squareRow} labels={copy} palette={palette}
            onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
            renderRating={renderRating} renderActionIcon={renderActionIcon} readOnly={readOnly} />
        </View>)}
      </View>
      : <View style={[styles.rowEmpty, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
        <Text style={[styles.rowEmptyText, { color: palette.textMuted }]}>{emptyLabel}</Text>
      </View>}
    <Text style={styles.rowKey} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">{row.key}</Text>
  </View>;
}

export function DiscoverRows({
  rows = [],
  loading = false,
  labels,
  palette,
  ...cardProps
}) {
  if (loading && !rows.length) return <DiscoverState kind="loading" labels={labels} palette={palette} />;
  if (!rows.length) return <DiscoverState kind="empty" labels={labels} palette={palette} />;
  return <View style={styles.rows}>
    {rows.map(row => <DiscoverRow key={row.key} row={row} labels={labels} palette={palette} {...cardProps} />)}
  </View>;
}

export function DiscoverHidden({
  entries = [],
  count,
  countLabel: countLabelOverride,
  labels,
  palette: paletteOverrides,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  initialGridWidth = 0,
}) {
  const [gridWidth, setGridWidth] = useState(initialGridWidth || 0);
  const onGridLayout = useCallback(event => {
    const width = event?.nativeEvent?.layout?.width || 0;
    setGridWidth(current => (Math.abs(current - width) < 0.5 ? current : width));
  }, []);
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const total = count == null ? entries.length : count;
  const totalLabel = countLabelOverride || countLabel(copy, total);
  const { cardWidth, gap } = mediaGridMetrics(gridWidth);
  if (!entries.length) {
    return <View style={styles.hidden}>
      <View style={styles.hiddenHeading}>
        <View style={styles.hiddenHeadingText}>
          <Text role="heading" aria-level={2} style={[styles.hiddenTitle, { color: palette.text }]}>{copy.hiddenTitle}</Text>
          <Text style={[styles.hiddenBody, { color: palette.textMuted }]}>{copy.hiddenBody}</Text>
        </View>
        <Text style={[styles.hiddenCount, { color: palette.textMuted }]}>{totalLabel}</Text>
      </View>
      <DiscoverState kind="hidden-empty" labels={labels} palette={palette} />
    </View>;
  }
  return <View style={styles.hidden}>
    <View style={styles.hiddenHeading}>
      <View style={styles.hiddenHeadingText}>
        <Text role="heading" aria-level={2} style={[styles.hiddenTitle, { color: palette.text }]}>{copy.hiddenTitle}</Text>
        <Text style={[styles.hiddenBody, { color: palette.textMuted }]}>{copy.hiddenBody}</Text>
      </View>
      <Text style={[styles.hiddenCount, { color: palette.textMuted }]}>{totalLabel}</Text>
    </View>
    <View style={[styles.hiddenGrid, { gap }]} onLayout={onGridLayout}>
      {entries.map((entry, index) => <View key={entry.cardKey || entry.key || index}
        style={[styles.hiddenCard, cardWidth ? { width: cardWidth } : null]}>
        <DiscoverCard model={entry} width={cardWidth}
          square={entry.mediaType === 'music' || entry.mediaType === 'podcast'}
          labels={copy} palette={palette}
          onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
          renderRating={renderRating} renderActionIcon={renderActionIcon} />
      </View>)}
    </View>
  </View>;
}

export function DiscoverPreview({
  row,
  labels,
  palette: paletteOverrides,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  return <View nativeID="rss-preview-row">
    <Rail title={row?.title} summary={row?.why} items={row?.items || []} itemWidth={168}
      emptyLabel={copy.previewEmpty}
      scrollLeftLabel="Scroll left" scrollRightLabel="Scroll right"
      palette={palette}
      renderItem={item => <DiscoverCard model={item} width={168} labels={copy} palette={palette}
        onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
        renderRating={renderRating} renderActionIcon={renderActionIcon} />} />
  </View>;
}

function ToolbarButton({ label, onPress, disabled, palette, primary = false, children }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{ disabled: !!disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => [styles.toolbarButton, {
      backgroundColor: primary ? (palette.accentStrong || palette.accent) : palette.surface,
      borderColor: primary ? (palette.accentStrong || palette.accent) : palette.border,
      opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
    }]}>
    {children || <Text style={[styles.toolbarText, { color: primary ? palette.accentText : palette.textSecondary }]}>{label}</Text>}
  </Pressable>;
}

export function DiscoverScreen({
  mediaOptions = [],
  selectedMediaType = 'all',
  onSelectMedia,
  showMore = false,
  onToggleShowMore,
  onRefresh,
  refreshing = false,
  cacheRefreshing = false,
  refreshStatus,
  toast,
  rows = [],
  hidden = { entries: [], count: 0 },
  loading = false,
  search = null,
  labels,
  palette: paletteOverrides,
  toastStyle,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  onUndo,
  onDismissRefreshStatus,
  onDismissToast,
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const isHidden = selectedMediaType === 'hidden';
  return <View style={styles.screen}>
    {search}
    {!isHidden ? <View style={styles.toolbar}>
      <ToolbarButton label={showMore ? copy.showFewer : copy.showMore}
        primary onPress={onToggleShowMore} disabled={refreshing} palette={palette} />
      <ToolbarButton label={copy.refresh} onPress={onRefresh}
        disabled={refreshing} palette={palette}>
        <Icon spec={actionIcons.refresh} color={palette.textMuted} size={20} />
      </ToolbarButton>
    </View> : null}
    <DiscoverTabs items={mediaOptions} selected={selectedMediaType} onSelect={onSelectMedia}
      label={copy.mediaType} labels={labels} palette={palette} />
    <DiscoverFeedback refreshing={refreshing} cacheRefreshing={cacheRefreshing && !isHidden}
      refreshStatus={refreshStatus} toast={toast} labels={labels} palette={palette}
      toastStyle={toastStyle} onDismissRefreshStatus={onDismissRefreshStatus}
      onDismissToast={onDismissToast} onUndo={onUndo} />
    {isHidden
      ? <DiscoverHidden entries={hidden.entries || []} count={hidden.count}
        countLabel={hidden.countLabel} labels={labels}
        palette={palette} onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction}
        onRate={onRate} renderRating={renderRating} renderActionIcon={renderActionIcon} />
      : <DiscoverRows rows={rows} loading={loading} labels={labels} palette={palette}
        onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
        renderRating={renderRating} renderActionIcon={renderActionIcon} />}
  </View>;
}

const styles = StyleSheet.create({
  screen: { gap: 16 },
  tabs: { gap: 4 },
  tabRow: { gap: 8, paddingVertical: 0, paddingRight: 8 },
  tab: { borderRadius: 9999, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 6 },
  tabText: { fontSize: 14, lineHeight: 20, fontWeight: '400' },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  toolbarButton: { minHeight: 36, borderRadius: 6, borderWidth: 1, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  toolbarText: { fontSize: 13, fontWeight: '600' },
  refreshGlyph: { fontSize: 18, lineHeight: 20 },
  feedbackStack: { gap: 8 },
  dismissButton: { padding: 4 },
  dismissText: { fontSize: 13, fontWeight: '600' },
  toast: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10,
    flexDirection: 'row', alignItems: 'center', gap: 8 },
  toastText: { flex: 1, fontSize: 13, lineHeight: 18 },
  rows: { gap: 32 },
  row: { gap: 12 },
  rowHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 },
  rowHeadingText: { flex: 1, minWidth: 0, gap: 4 },
  rowTitle: { fontSize: 20, fontWeight: '600', lineHeight: 28 },
  rowMeta: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16 },
  rowWhy: { fontSize: 14, lineHeight: 20, flexShrink: 1 },
  rowSignal: { fontSize: 12, lineHeight: 16, flexShrink: 0 },
  rowStale: { fontSize: 12, lineHeight: 16, flexShrink: 0 },
  rowGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: gridGap },
  rowGridItem: { minWidth: 0 },
  rowEmpty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, paddingHorizontal: 16, paddingVertical: 20 },
  rowEmptyText: { fontSize: 14, lineHeight: 20 },
  rowKey: { display: 'none' },
  hidden: { gap: 12 },
  hiddenHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  hiddenHeadingText: { flex: 1, gap: 2 },
  hiddenTitle: { fontSize: 24, fontWeight: '600', lineHeight: 30 },
  hiddenBody: { fontSize: 14, lineHeight: 19 },
  hiddenCount: { fontSize: 14, lineHeight: 19, flexShrink: 0 },
  hiddenGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: gridGap },
  hiddenCard: { minWidth: 0 },
  state: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 16, paddingVertical: 20, alignItems: 'center', gap: 4 },
  stateTitle: { fontSize: 16, fontWeight: '600', lineHeight: 21, textAlign: 'center' },
  stateBody: { fontSize: 13, lineHeight: 18, textAlign: 'center' },
  srOnly: { position: 'absolute', width: 0, height: 0, overflow: 'hidden', opacity: 0 },
});
