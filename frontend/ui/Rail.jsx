import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Spinner } from './Spinner';

// Native loads every mounted image at once, a few at a time in order, so a row
// of 14 covers keeps the ones a person is waiting for in a queue. Mount only the
// cards near the visible window; the rest fill in as the row scrolls. Carve-out:
// web mounts every card because its <img loading="lazy"> already loads only nearby covers.
// The native app passes `windowCards`; the web leaves it off.
const WINDOW_BUFFER = 3;
const INITIAL_WINDOW = 7;

const sortHitSlop = { top: 14, bottom: 14, left: 10, right: 12 };

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceHover: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  arrow: '#d4d4d8',
  arrowDisabled: '#52525b',
  loading: '#6366f1',
  focus: '#6366f1',
};

export function Rail({
  items = [],
  renderItem,
  title,
  titleDetail,
  summary,
  summaryInline,
  direction = 'desc',
  total,
  loadedCount,
  hasMore,
  loadingMore = false,
  sorting = false,
  windowCards = false,
  loadMoreThreshold = 1152,
  itemWidth = 176,
  getItemWidth,
  itemGap = 16,
  viewAll,
  onSort,
  sortLabel,
  onTitlePress,
  onLoadMore,
  loadingLabel = 'Loading more',
  emptyLabel,
  collapsible = false,
  collapsed,
  defaultCollapsed = false,
  onCollapsedChange,
  collapseLabel = 'Toggle section',
  scrollLeftLabel = 'Scroll left',
  scrollRightLabel = 'Scroll right',
  accessibilityLabel,
  palette: paletteOverrides,
  scrollRef,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const viewport = useWindowDimensions();
  // Release drops shelf headings to the base size on phones.
  const compact = viewport.width < 640;
  const localScrollRef = useRef(null);
  const resolvedScrollRef = scrollRef || localScrollRef;
  const metricsRef = useRef({ x: 0, width: 0, content: 0 });
  const loadGuard = useRef(false);
  const [metrics, setMetrics] = useState({ x: 0, width: 0, content: 0 });
  // One-line header: when the sort label cannot sit beside the title it
  // collapses to its arrow, so at most the title detail ever truncates.
  const [rowWidth, setRowWidth] = useState(0);
  const [groupWidth, setGroupWidth] = useState(0);
  const [sortFullWidth, setSortFullWidth] = useState(0);
  const collapseSort = Boolean(summaryInline) && rowWidth > 0 && groupWidth > 0 && sortFullWidth > 0
    && groupWidth + sortFullWidth + 14 > rowWidth;
  const [uncontrolledCollapsed, setUncontrolledCollapsed] = useState(defaultCollapsed);
  const isCollapsed = collapsed === undefined ? uncontrolledCollapsed : collapsed;

  const knownLimit = Number.isFinite(total) && Number.isFinite(loadedCount);
  const canLoadMore = hasMore === false
    ? false
    : hasMore === true
      ? true
      : knownLimit
        ? loadedCount < total
        : Boolean(onLoadMore);

  const label = accessibilityLabel || (titleDetail ? `${title} • ${titleDetail}` : title);

  useEffect(() => {
    loadGuard.current = false;
  }, [items.length, hasMore, loadingMore]);

  const requestMore = useCallback(() => {
    if (!onLoadMore || !canLoadMore || loadingMore || loadGuard.current) return;
    const { x, width, content } = metricsRef.current;
    if (width <= 0 || content <= 0) return;
    if (content > width + 1 && x + width < content - loadMoreThreshold) return;
    loadGuard.current = true;
    onLoadMore();
  }, [onLoadMore, canLoadMore, loadingMore, loadMoreThreshold]);

  const updateMetrics = useCallback(next => {
    metricsRef.current = next;
    setMetrics(current => (
      current.x === next.x && current.width === next.width && current.content === next.content
        ? current
        : next
    ));
  }, []);

  function handleScroll(event) {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    updateMetrics({
      x: contentOffset.x,
      width: layoutMeasurement.width,
      content: contentSize.width,
    });
    if (contentOffset.x + layoutMeasurement.width >= contentSize.width - loadMoreThreshold) {
      requestMore();
    }
  }

  function handleContentSizeChange(content) {
    const next = { ...metricsRef.current, content };
    updateMetrics(next);
    if (content <= next.width + 1) requestMore();
  }

  function handleLayout(event) {
    const next = { ...metricsRef.current, width: event.nativeEvent.layout.width };
    updateMetrics(next);
    if (next.content <= next.width + 1) requestMore();
  }

  function scrollByPage(delta) {
    const { x, width, content } = metricsRef.current;
    if (width <= 0) return;
    const max = Math.max(0, content - width);
    const target = Math.max(0, Math.min(max, x + delta * width * 0.9));
    const node = resolvedScrollRef.current;
    if (node?.scrollTo) node.scrollTo({ x: target, y: 0, animated: true });
    else if (node?.scrollToOffset) node.scrollToOffset({ offset: target, animated: true });
  }

  function toggleCollapsed() {
    const next = !isCollapsed;
    if (collapsed === undefined) setUncontrolledCollapsed(next);
    onCollapsedChange?.(next);
  }

  const atStart = metrics.x <= 2;
  const atEnd = metrics.content > 0 && metrics.x + metrics.width >= metrics.content - 4;
  const canScrollPrev = !atStart;
  const canScrollNext = canLoadMore || (metrics.content > metrics.width + 1 && !atEnd);
  const mountedCards = !windowCards ? items.length
    : metrics.width > 0
      ? Math.ceil((metrics.x + metrics.width) / (itemWidth + itemGap)) + WINDOW_BUFFER
      : INITIAL_WINDOW;
  const onGroupLayout = event => setGroupWidth(event.nativeEvent.layout.width);
  const groupStyle = [styles.titleLink, { maxWidth: collapseSort && rowWidth > 0 ? Math.max(rowWidth - 32, 0) : '100%' }];
  const titleContent = <>
    <Text role="heading" aria-level={3} numberOfLines={1} style={[styles.title, compact && styles.titleCompact, { color: palette.text }]}>{title}</Text>
    {titleDetail ? <>
      <Text aria-hidden style={[styles.bullet, compact && styles.titleCompact, { color: palette.text }]}>•</Text>
      <Text role="heading" aria-level={3} numberOfLines={1} style={[styles.detail, compact && styles.titleCompact, { color: palette.text }]}>{titleDetail}</Text>
    </> : null}
  </>;

  return <View style={styles.wrapper} testID={testID}>
    {(title || summaryInline || viewAll || collapsible) ? <View style={styles.headingRow}>
      <View style={styles.headingText}>
        <View style={styles.titleRow} onLayout={event => setRowWidth(event.nativeEvent.layout.width)}>
          {onTitlePress ? <Pressable accessibilityRole="link" accessibilityLabel={label}
            onPress={onTitlePress} onLayout={onGroupLayout} style={groupStyle}>{titleContent}</Pressable>
            : <View onLayout={onGroupLayout} style={groupStyle}>{titleContent}</View>}
          {summaryInline ? (onSort
            ? <Pressable accessibilityRole="button" accessibilityLabel={sortLabel || summaryInline}
              onPress={onSort} hitSlop={sortHitSlop}
              style={({ pressed }) => [styles.sortButton, pressed && styles.pressed]}
              onLayout={event => { if (!collapseSort && !sorting) setSortFullWidth(event.nativeEvent.layout.width); }}>
              {collapseSort ? null : <Text numberOfLines={1} style={[styles.summaryInline, { color: palette.textMuted }]}>{summaryInline}</Text>}
              <Text aria-hidden style={[styles.sortIcon, { color: palette.textMuted }]}>{direction === 'asc' ? '▲' : '▼'}</Text>
              {sorting ? <Spinner size={14} color={palette.loading} /> : null}
            </Pressable>
            : <Text numberOfLines={1} style={[styles.summaryInline, { color: palette.textMuted }]}>{summaryInline}</Text>) : null}
          {viewAll ? <Pressable accessibilityRole="link" accessibilityLabel={viewAll.accessibilityLabel || viewAll.label}
            onPress={viewAll.onPress} style={styles.sortButton}>
            <Text style={[styles.summaryInline, { color: palette.link || palette.accent }]}>{viewAll.label}</Text>
          </Pressable> : null}
        </View>
        {summary ? <Text style={[styles.summary, { color: palette.textMuted }]}>{summary}</Text> : null}
      </View>
      <View style={styles.controls}>
        <Pressable accessibilityRole="button" accessibilityLabel={scrollLeftLabel}
          accessibilityState={{ disabled: !canScrollPrev }} disabled={!canScrollPrev}
          onPress={() => scrollByPage(-1)} style={[styles.iconButton, !canScrollPrev && styles.hiddenControl]}>
          <Text aria-hidden style={[styles.arrow, { color: palette.arrow }]}>‹</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={scrollRightLabel}
          accessibilityState={{ disabled: !canScrollNext }} disabled={!canScrollNext}
          onPress={() => scrollByPage(1)} style={[styles.iconButton, !canScrollNext && styles.hiddenControl]}>
          <Text aria-hidden style={[styles.arrow, { color: palette.arrow }]}>›</Text>
        </Pressable>
        {collapsible ? <Pressable accessibilityRole="button" accessibilityLabel={collapseLabel}
          accessibilityState={{ expanded: !isCollapsed }} onPress={toggleCollapsed}
          style={[styles.iconButton, styles.toggleButton]}>
          <Text aria-hidden style={[styles.chevron, { color: palette.textMuted, transform: [{ rotate: isCollapsed ? '0deg' : '180deg' }] }]}>⌄</Text>
        </Pressable> : null}
      </View>
    </View> : null}
    {!isCollapsed ? <View accessibilityRole="list" accessibilityLabel={label} accessibilityState={{ busy: sorting }}
      pointerEvents={sorting ? 'none' : 'auto'} style={sorting ? styles.sorting : undefined}>
      <ScrollView ref={resolvedScrollRef} horizontal nestedScrollEnabled
        showsHorizontalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={handleScroll}
        onContentSizeChange={handleContentSizeChange}
        onLayout={handleLayout}
        contentContainerStyle={[styles.scroller, { gap: itemGap }]}>
        {items.map((item, index) => <View key={item?.id ?? index} style={[styles.item, { width: getItemWidth ? getItemWidth(item) : itemWidth }]}>
          {index < mountedCards ? renderItem?.(item, index) : null}
        </View>)}
        {loadingMore ? <View style={styles.loading}>
          <Spinner size={16} color={palette.loading} />
          <Text accessibilityLiveRegion="polite" style={[styles.loadingText, { color: palette.textMuted }]}>{loadingLabel}</Text>
        </View> : null}
        {!items.length && !loadingMore && emptyLabel
          ? <Text style={[styles.empty, { color: palette.textMuted }]}>{emptyLabel}</Text>
          : null}
      </ScrollView>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { gap: 8 },
  headingRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  headingText: { flex: 1, minWidth: 0, gap: 2 },
  titleRow: { flexDirection: 'row', flexWrap: 'nowrap', alignItems: 'baseline', columnGap: 8, minWidth: 0 },
  titleLink: { flexDirection: 'row', flexWrap: 'nowrap', alignItems: 'baseline', columnGap: 8, flexShrink: 0, minWidth: 0 },
  title: { fontSize: 18, fontWeight: '600', lineHeight: 18, flexShrink: 0.2, minWidth: 0 },
  titleCompact: { fontSize: 16, lineHeight: 21.6 },
  bullet: { fontSize: 18, fontWeight: '600', lineHeight: 18, flexShrink: 0 },
  detail: { fontSize: 18, fontWeight: '600', lineHeight: 18, flexShrink: 1, minWidth: 0 },
  summary: { fontSize: 13, lineHeight: 18 },
  summaryInline: { fontSize: 14, fontWeight: '500', lineHeight: 14 },
  sortButton: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginLeft: 6, flexShrink: 0 },
  sortIcon: { fontSize: 16, lineHeight: 16 },
  sorting: { opacity: 0.45 },
  pressed: { opacity: 0.55 },
  controls: { flexDirection: 'row', alignItems: 'center', gap: 2, flexShrink: 0 },
  iconButton: { padding: 4, borderRadius: 4 },
  toggleButton: { marginLeft: 4 },
  disabled: { opacity: 0.4 },
  hiddenControl: { opacity: 0 },
  arrow: { fontSize: 20, lineHeight: 20 },
  chevron: { fontSize: 16, lineHeight: 16 },
  scroller: { paddingBottom: 12, paddingRight: 8, alignItems: 'flex-start' },
  item: { flexShrink: 0 },
  loading: { width: 56, alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center', gap: 4 },
  loadingText: { fontSize: 10 },
  empty: { fontSize: 13, lineHeight: 18 },
});
