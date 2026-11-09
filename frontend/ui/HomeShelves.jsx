import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MediaCard } from './MediaCard.jsx';
import { Rail } from './Rail';

// Web and native shelves must pick the same card width. Web computes it from
// the phone breakpoint in mountHome; native passes the same value from here.
export const SHELF_BREAKPOINTS = { phone: 640 };
export const SHELF_CARD_WIDTHS = { phone: 110, default: 176 };
export function shelfCardWidth(viewportWidth) {
  return viewportWidth < SHELF_BREAKPOINTS.phone
    ? SHELF_CARD_WIDTHS.phone
    : SHELF_CARD_WIDTHS.default;
}

// Video and mixed-media shelves keep the release card widths: landscape video
// rows are 17rem, mixed rows give square artwork 16.5rem and video 29.33rem.
// On phones they scale from the poster width the way the release CSS did.
export function railItemWidth(row, item, baseWidth) {
  const phone = baseWidth <= SHELF_CARD_WIDTHS.phone;
  if (row?.videoLandscape) return phone ? 168 : 272;
  if (row?.mixedMedia) {
    if (item?.card?.video) return phone ? Math.round((baseWidth * 8) / 3) : 469;
    if (item?.card?.shape === 'square') return phone ? Math.round(baseWidth * 1.5) : 264;
  }
  return baseWidth;
}

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceHover: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  arrow: '#d4d4d8',
  arrowDisabled: '#52525b',
  loading: '#6366f1',
  focus: '#6366f1',
};

const DEFAULT_LABELS = {
  scrollLeft: 'Scroll left',
  scrollRight: 'Scroll right',
  loadingMore: 'Loading more',
  artworkRefreshing: 'Refreshing artwork...',
  unableToLoad: 'Unable to load this row.',
  retry: 'Try again',
  emptyTitle: 'Nothing is configured for Home yet',
  emptyHint: 'Add or enable rows from the Home Screen settings page to populate this view.',
  openSettings: 'Open Home Screen Settings',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function rowKey(row) {
  return String(row?.rowId ?? row?.row_id ?? '');
}

function rowLoaded(row) {
  const total = Number(row?.total);
  const loaded = Number(row?.loadedCount ?? row?.loaded_count);
  if (Number.isFinite(total) && Number.isFinite(loaded)) return loaded >= total;
  return !row?.hasMore;
}

function sortLabel(row, labels) {
  const title = row?.titleMain || row?.title || '';
  const detail = row?.titleDetail ? ` • ${row.titleDetail}` : '';
  return `${labels.toggleSort || 'Toggle sort direction for'} ${title}${detail}`;
}

function RailRow({
  row,
  labels,
  palette,
  readOnly,
  itemWidth,
  loadingMore,
  renderCard,
  renderProgress,
  renderRating,
  renderActionIcon,
  railComponent,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  onSortRow,
  onLoadMore,
  RailComponent = Rail,
}) {
  const items = row.items || [];
  const hasMore = !rowLoaded(row);
  return <RailComponent
    title={row.titleMain || row.title}
    titleDetail={row.titleDetail}
    summaryInline={row.summaryInline}
    direction={row.direction}
    total={row.total}
    loadedCount={row.loadedCount}
    hasMore={hasMore}
    loadingMore={loadingMore}
    itemWidth={itemWidth}
    getItemWidth={item => railItemWidth(row, item, itemWidth)}
    items={items}
    onSort={onSortRow ? () => onSortRow(row) : undefined}
    sortLabel={sortLabel(row, labels)}
    onLoadMore={onLoadMore ? () => onLoadMore(row) : undefined}
    loadingLabel={labels.loadingMore}
    emptyLabel={labels.rowEmpty || 'Nothing here yet.'}
    accessibilityLabel={row.titleDetail ? `${row.titleMain || row.title} • ${row.titleDetail}` : (row.titleMain || row.title)}
    scrollLeftLabel={labels.scrollLeft}
    scrollRightLabel={labels.scrollRight}
    palette={palette}
    renderItem={item => <View style={styles.cardStack}>
      {renderCard
        ? renderCard(item, row)
        : <MediaCard model={item.card} labels={labels} palette={palette}
          width={itemWidth} readOnly={readOnly}
          onOpen={() => onOpenCard?.(item, row)}
          onOpenLink={href => onOpenLink?.(href, item, row)}
          onAction={action => onAction?.(action, item, row)}
          onRate={score => onRate?.(score, item, row)}
          renderRating={renderRating}
          renderActionIcon={renderActionIcon} />}
      {item.progress && renderProgress ? <View nativeID={item.progress.target}
        style={styles.progress}>
        {renderProgress(item.progress, item, row)}
      </View> : null}
    </View>} />;
}

function DeferredRow({ labels, palette, itemWidth = 176 }) {
  return <View style={styles.skeleton}
    accessibilityRole="progressbar" accessibilityLabel={labels.loadingRow || 'Loading row'}>
    <View style={[styles.skeletonTitle, { backgroundColor: palette.surfaceStrong }]} />
    <View style={styles.skeletonCards}>
      {[0, 1, 2, 3].map(index => <View key={index}
        style={[styles.skeletonCard, { backgroundColor: palette.surface, width: itemWidth }]} />)}
    </View>
  </View>;
}

export function HomeShelves({
  groups = [],
  deferredGroups = [],
  showMediaTypeHeaders = false,
  labels: suppliedLabels,
  palette: suppliedPalette,
  readOnly = false,
  itemWidth = 176,
  refreshDelayMs = 1000,
  refreshIntervalMs = 30000,
  deferredDelayMs = 120,
  renderCard,
  renderProgress,
  renderRating,
  renderActionIcon,
  railComponent,
  onOpenCard,
  onOpenLink,
  onAction,
  onRate,
  onSortRow,
  onLoadMore,
  onLoadRow,
  onRefreshCovers,
  onOpenSettings,
  testID,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  // Release separates media-type groups by 1rem on phones and 2rem from `sm`.
  const viewport = useWindowDimensions();
  const sectionGap = viewport.width >= 640 ? 32 : 16;
  const [loadedRows, setLoadedRows] = useState({});
  const [rowPatches, setRowPatches] = useState({});
  const [pendingRows, setPendingRows] = useState({});
  const [rowErrors, setRowErrors] = useState({});
  const [loadingMore, setLoadingMore] = useState({});
  const [sorting, setSorting] = useState({});
  const startedRows = useRef(new Set());
  const firstPoll = useRef(true);
  const loadRowRef = useRef(null);
  const pollRowsRef = useRef([]);

  const deferredKey = useMemo(
    () => deferredGroups.map(group => `${group.mediaType}:${(group.rowIds || []).join(',')}`).join('|'),
    [deferredGroups],
  );

  useEffect(() => {
    startedRows.current = new Set();
  }, [deferredKey]);

  const effectiveRow = useCallback(row => {
    const key = rowKey(row);
    return rowPatches[key] || row;
  }, [rowPatches]);

  const allRows = useMemo(() => [
    ...groups.flatMap(group => group.rows || []),
    ...deferredGroups.flatMap(group => (group.rowIds || [])
      .map(id => loadedRows[String(id)])
      .filter(Boolean)),
  ], [groups, deferredGroups, loadedRows]);

  const pollRows = useMemo(
    () => allRows.map(effectiveRow).filter(row => row && row.pollForCovers),
    [allRows, effectiveRow],
  );
  pollRowsRef.current = pollRows;
  const pollIdsKey = pollRows.map(row => rowKey(row)).join(',');
  const unresolved = deferredGroups.flatMap(group => (group.rowIds || [])
    .filter(id => !Object.prototype.hasOwnProperty.call(loadedRows, String(id))
      && !rowErrors[String(id)])).length;

  const loadRow = useCallback(async id => {
    const key = String(id);
    if (!onLoadRow || pendingRows[key]) return;
    setPendingRows(current => ({ ...current, [key]: true }));
    setRowErrors(current => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    try {
      const row = await onLoadRow(id);
      setLoadedRows(current => ({ ...current, [key]: row || null }));
    } catch (error) {
      startedRows.current.delete(key);
      setRowErrors(current => ({ ...current, [key]: true }));
    } finally {
      setPendingRows(current => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  }, [onLoadRow, pendingRows]);

  loadRowRef.current = loadRow;

  useEffect(() => {
    if (!onLoadRow) return undefined;
    const timers = [];
    const ids = deferredGroups.flatMap(group => group.rowIds || []);
    ids.forEach((id, index) => {
      const key = String(id);
      if (startedRows.current.has(key)) return;
      startedRows.current.add(key);
      timers.push(setTimeout(() => { loadRowRef.current?.(id); }, index * deferredDelayMs));
    });
    return () => timers.forEach(timer => clearTimeout(timer));
  }, [deferredKey, deferredDelayMs, onLoadRow]);

  const applyRow = useCallback(row => {
    if (!row) return;
    const key = rowKey(row);
    setRowPatches(current => ({ ...current, [key]: row }));
    setLoadedRows(current => (Object.prototype.hasOwnProperty.call(current, key)
      ? { ...current, [key]: row }
      : current));
  }, []);

  const loadMore = useCallback(async row => {
    const key = rowKey(row);
    if (!onLoadMore || loadingMore[key] || rowLoaded(row)) return;
    setLoadingMore(current => ({ ...current, [key]: true }));
    try {
      const next = await onLoadMore(row);
      if (next) applyRow(next);
    } finally {
      setLoadingMore(current => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  }, [applyRow, loadingMore, onLoadMore]);

  const sortRow = useCallback(async row => {
    const key = rowKey(row);
    if (!onSortRow || sorting[key]) return;
    setSorting(current => ({ ...current, [key]: true }));
    try {
      const next = await onSortRow(row);
      if (next) applyRow(next);
    } finally {
      setSorting(current => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  }, [applyRow, onSortRow, sorting]);

  const pollReady = pollRows.length > 0 || unresolved > 0;
  useEffect(() => {
    if (!onRefreshCovers || !pollReady) return undefined;
    let cancelled = false;
    let timer = null;
    const delay = firstPoll.current ? refreshDelayMs : refreshIntervalMs;
    firstPoll.current = false;
    async function poll() {
      try {
        const result = await onRefreshCovers(pollRowsRef.current.map(row => rowKey(row)), unresolved);
        if (!cancelled && result) {
          (result.rows || []).forEach(applyRow);
          if (result.pollRowIds) {
            const next = new Set(result.pollRowIds.map(String));
            setRowPatches(current => {
              const updates = {};
              Object.entries(current).forEach(([key, row]) => {
                if (row && next.has(key) !== !!row.pollForCovers) {
                  updates[key] = { ...row, pollForCovers: next.has(key) };
                }
              });
              return Object.keys(updates).length ? { ...current, ...updates } : current;
            });
          }
        }
      } catch (error) {
        // A failed poll must not stop cover refreshes; the next interval retries.
      }
      if (!cancelled) timer = setTimeout(poll, refreshIntervalMs);
    }
    timer = setTimeout(poll, delay);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [applyRow, onRefreshCovers, pollIdsKey, pollReady, refreshDelayMs, refreshIntervalMs, unresolved]);

  function renderBuiltRows(rows) {
    return (rows || []).map(row => <RailRow key={rowKey(row)} row={effectiveRow(row)}
      labels={labels} palette={palette} readOnly={readOnly} itemWidth={itemWidth}
      loadingMore={!!loadingMore[rowKey(row)]}
      renderCard={renderCard} renderProgress={renderProgress}
      renderRating={renderRating} renderActionIcon={renderActionIcon}
      RailComponent={railComponent}
      onOpenCard={onOpenCard} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
      onSortRow={onSortRow ? sortRow : undefined}
      onLoadMore={onLoadMore ? loadMore : undefined} />);
  }

  function renderDeferredRow(group, id) {
    const key = String(id);
    if (Object.prototype.hasOwnProperty.call(loadedRows, key)) {
      const row = loadedRows[key];
      return row ? renderBuiltRows([row])[0] : null;
    }
    if (rowErrors[key]) {
      return <View key={`error-${key}`} style={[styles.error, { borderColor: palette.border }]}>
        <Text style={[styles.errorText, { color: palette.textMuted }]}>{labels.unableToLoad}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.retry}
          onPress={() => { startedRows.current.delete(key); loadRow(id); }}
          style={({ pressed }) => [styles.retry, {
            backgroundColor: palette.surfaceStrong,
            opacity: pressed ? 0.7 : 1,
          }]}>
          <Text style={[styles.retryText, { color: palette.text }]}>{labels.retry}</Text>
        </Pressable>
      </View>;
    }
    return <DeferredRow key={`pending-${key}`} group={group} rowId={id} labels={labels}
      palette={palette} itemWidth={itemWidth} />;
  }

  function sectionHeader(group) {
    if (!showMediaTypeHeaders) return null;
    return <View style={[styles.groupHeader, { borderColor: palette.border }]}>
      <Text role="heading" aria-level={2} style={[styles.groupTitle, { color: palette.text }]}>
        {group.label}
      </Text>
    </View>;
  }

  const hasContent = groups.some(group => (group.rows || []).length)
    || deferredGroups.some(group => (group.rowIds || []).length);
  if (!hasContent) {
    return <View style={[styles.empty, { backgroundColor: palette.surface, borderColor: palette.border }]}
      testID={testID}>
      <Text style={[styles.emptyTitle, { color: palette.text }]}>{labels.emptyTitle}</Text>
      <Text style={[styles.emptyHint, { color: palette.textMuted }]}>{labels.emptyHint}</Text>
      {onOpenSettings ? <Pressable accessibilityRole="button" accessibilityLabel={labels.openSettings}
        onPress={onOpenSettings} style={({ pressed }) => [styles.settingsButton, {
          backgroundColor: palette.accent,
          opacity: pressed ? 0.8 : 1,
        }]}>
        <Text style={styles.settingsButtonText}>{labels.openSettings}</Text>
      </Pressable> : null}
    </View>;
  }

  return <View style={[styles.stack, { gap: sectionGap }]} testID={testID}>
    {groups.map(group => <View key={group.mediaType} style={styles.group}>
      {sectionHeader(group)}
      {renderBuiltRows(group.rows)}
    </View>)}
    {deferredGroups.map(group => {
      const ids = group.rowIds || [];
      const hasRenderable = ids.some(id => {
        const key = String(id);
        return !Object.prototype.hasOwnProperty.call(loadedRows, key)
          || loadedRows[key] || rowErrors[key];
      });
      if (!hasRenderable) return null;
      return <View key={`deferred-${group.mediaType || group.label}`} style={styles.group}>
        {sectionHeader(group)}
        {ids.map(id => renderDeferredRow(group, id))}
      </View>;
    })}
    {pollRows.length ? <Text accessibilityLiveRegion="polite"
      style={[styles.polling, { color: palette.textMuted }]}>{labels.artworkRefreshing}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 24 },
  group: { gap: 12 },
  groupHeader: { borderBottomWidth: 1, paddingBottom: 10 },
  groupTitle: { fontSize: 24, fontWeight: '600', lineHeight: 30 },
  skeleton: { gap: 8 },
  skeletonTitle: { width: 160, height: 18, borderRadius: 4 },
  skeletonCards: { flexDirection: 'row', gap: 16, overflow: 'hidden' },
  cardStack: { gap: 0 },
  progress: { marginTop: 8, alignItems: 'center', justifyContent: 'center' },
  skeletonCard: { width: 176, aspectRatio: 2 / 3, borderRadius: 8 },
  error: { borderWidth: 1, borderRadius: 8, padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  errorText: { flex: 1, fontSize: 13 },
  retry: { borderRadius: 6, paddingHorizontal: 12, paddingVertical: 7 },
  retryText: { fontSize: 12, fontWeight: '600' },
  polling: { fontSize: 12 },
  empty: { borderWidth: 1, borderRadius: 10, padding: 28, alignItems: 'center', gap: 8 },
  emptyTitle: { fontSize: 19, fontWeight: '600', textAlign: 'center' },
  emptyHint: { fontSize: 13, textAlign: 'center', lineHeight: 18 },
  settingsButton: { borderRadius: 6, paddingHorizontal: 16, paddingVertical: 9, marginTop: 6 },
  settingsButtonText: { color: '#ffffff', fontSize: 13, fontWeight: '600' },
});
