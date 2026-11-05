import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Badge } from '../ui/Badge';
import { MediaCardView } from '../ui/MediaCardView';
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

function activeAppearance(palette, active) {
  return active
    ? { color: palette.accentText, backgroundColor: palette.accent, borderColor: palette.accent, borderWidth: 0 }
    : { color: palette.textSecondary, backgroundColor: palette.surface, borderColor: palette.border, borderWidth: 1 };
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
      {items.map(item => <Badge key={item.value} label={item.label} size="sm"
        accessibilityLabel={item.label}
        appearance={activeAppearance(palette, selected === item.value)}
        onPress={() => onSelect?.(item.value)} />)}
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
        <Text style={[styles.dismissText, { color: palette.textMuted }]}>✕</Text>
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
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  readOnly,
}) {
  return <MediaCardView model={model} width={width} labels={labels} palette={palette}
    readOnly={readOnly}
    onOpen={() => onOpenCard?.(model.href, model)}
    onOpenLink={href => onOpenLink?.(href)}
    onAction={action => onAction?.(model, action)}
    onRate={onRate ? score => onRate(model, score) : undefined}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon} />;
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
}) {
  if (!row) return null;
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const summary = [row.why, row.matchSignal].filter(Boolean).join(' • ');
  const emptyLabel = row.emptyLabel || (row.continueRow ? copy.rowEmptyContinue : copy.rowEmptyDefault);
  return <View nativeID={`discover-row-${row.key}`} style={styles.row}>
    <Rail title={row.title} summary={summary} summaryInline={row.isStale ? copy.refreshing : undefined}
      items={row.items || []} itemWidth={168}
      accessibilityLabel={`${row.title}${summary ? ` • ${summary}` : ''}`}
      emptyLabel={emptyLabel}
      scrollLeftLabel={copy.previous || 'Scroll left'}
      scrollRightLabel={copy.next || 'Scroll right'}
      palette={palette}
      renderItem={item => <DiscoverCard model={item} width={168} labels={copy} palette={palette}
        onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
        renderRating={renderRating} renderActionIcon={renderActionIcon} readOnly={readOnly} />} />
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
}) {
  const palette = resolvePalette(paletteOverrides);
  const copy = copyFor(labels);
  const total = count == null ? entries.length : count;
  const totalLabel = countLabelOverride || countLabel(copy, total);
  if (!entries.length) {
    return <View style={styles.hidden}>
      <View style={styles.hiddenHeading}>
        <View style={styles.hiddenHeadingText}>
          <Text role="heading" aria-level={2} style={[styles.hiddenTitle, { color: palette.text }]}>{copy.hiddenTitle}</Text>
          <Text style={[styles.hiddenBody, { color: palette.textMuted }]}>{copy.hiddenBody}</Text>
        </View>
        <Badge label={totalLabel} size="sm" appearance={{
          color: palette.textSecondary, backgroundColor: palette.surface,
          borderColor: palette.border, borderWidth: 1,
        }} />
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
      <Badge label={totalLabel} size="sm" appearance={{
        color: palette.textSecondary, backgroundColor: palette.surface,
        borderColor: palette.border, borderWidth: 1,
      }} />
    </View>
    <View style={styles.hiddenGrid}>
      {entries.map((entry, index) => <View key={entry.cardKey || entry.key || index} style={styles.hiddenCard}>
        <DiscoverCard model={entry} width={160} labels={copy} palette={palette}
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
      backgroundColor: primary ? palette.accent : palette.surface,
      borderColor: primary ? palette.accent : palette.border,
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
        <Text style={[styles.refreshGlyph, { color: palette.textMuted }]}>{refreshing ? '↻' : '⟳'}</Text>
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
  tabRow: { gap: 8, paddingVertical: 2, paddingRight: 8 },
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
  rows: { gap: 24 },
  row: { gap: 8 },
  rowKey: { height: 0, opacity: 0 },
  hidden: { gap: 12 },
  hiddenHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  hiddenHeadingText: { flex: 1, gap: 2 },
  hiddenTitle: { fontSize: 20, fontWeight: '700', lineHeight: 25 },
  hiddenBody: { fontSize: 13, lineHeight: 18 },
  hiddenGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  hiddenCard: { width: 160 },
  state: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 16, paddingVertical: 20, alignItems: 'center', gap: 4 },
  stateTitle: { fontSize: 16, fontWeight: '600', lineHeight: 21, textAlign: 'center' },
  stateBody: { fontSize: 13, lineHeight: 18, textAlign: 'center' },
  srOnly: { height: 0, opacity: 0 },
});
