import React from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { MediaCard } from './MediaCard';
import { ParentPicker } from './ParentPicker';
import { Spinner } from './Spinner';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentText: '#ffffff',
  link: '#818cf8',
  danger: '#ef4444',
  radius: 8,
};

const defaultLabels = {
  title: 'Search Results',
  source: 'Source:',
  searchOnline: 'Search online',
  emptyTitle: 'No results found',
  emptyBody: 'Try checking your spelling or using different keywords.',
  loading: 'Loading results…',
  errorTitle: 'Search could not load',
  errorBody: 'Please try again.',
  retry: 'Try again',
  loadMore: 'Load more',
  loadingMore: 'Loading more…',
  previous: 'Previous page',
  next: 'Next page',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  parentTitle: 'Pick a parent',
  parentPlaceholder: 'Search for a parent…',
  parentEmpty: 'No matches found.',
  parentLoading: 'Loading matches…',
  parentErrorTitle: 'Parent search could not load',
  parentErrorBody: 'Please try again.',
  parentSelected: 'Selected',
};

function ResultCard({
  item,
  layout,
  width,
  labels,
  palette,
  onOpenResult,
  onOpenLink,
  onAction,
  onReorder,
  onRate,
  renderRating,
  renderActionIcon,
}) {
  const model = layout === 'row' ? { ...item, layout: 'row' } : item;
  return <MediaCard
    model={model}
    width={width}
    labels={labels}
    palette={palette}
    onOpen={() => onOpenResult?.(item.href)}
    onOpenLink={href => onOpenLink?.(href)}
    onAction={onAction}
    onReorder={onReorder}
    onRate={score => onRate?.(item, score)}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon}
  />;
}

function ResultGroup({
  items = [],
  layout = 'grid',
  labels,
  palette,
  onOpenResult,
  onOpenLink,
  onAction,
  onReorder,
  onRate,
  renderRating,
  renderActionIcon,
}) {
  const { width } = useWindowDimensions();
  if (!items.length) return null;
  if (layout === 'list') {
    return <View style={styles.list}>
      {items.map((item, index) => <View
        key={item.cardKey || item.key || `${item.title}-${index}`}
        style={[styles.listRow, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <ResultCard
          item={item}
          layout="row"
          width={width}
          labels={labels}
          palette={palette}
          onOpenResult={onOpenResult}
          onOpenLink={onOpenLink}
          onAction={onAction}
          onReorder={onReorder}
          onRate={onRate}
          renderRating={renderRating}
          renderActionIcon={renderActionIcon}
        />
      </View>)}
    </View>;
  }
  const columns = width >= 920 ? 5 : width >= 720 ? 4 : width >= 520 ? 3 : 2;
  const cardWidth = Math.min(190, Math.max(128, (width - 40 - (columns - 1) * 12) / columns));
  return <View style={styles.grid}>
    {items.map((item, index) => <View key={item.cardKey || item.key || `${item.title}-${index}`}
      style={{ width: cardWidth }}>
      <ResultCard
        item={item}
        layout="grid"
        width={cardWidth}
        labels={labels}
        palette={palette}
        onOpenResult={onOpenResult}
        onOpenLink={onOpenLink}
        onAction={onAction}
        onReorder={onReorder}
        onRate={onRate}
        renderRating={renderRating}
        renderActionIcon={renderActionIcon}
      />
    </View>)}
  </View>;
}

function SectionHeading({ section, palette, labels, onSearchOnline }) {
  const hasMeta = section.totalLabel || section.shownLabel;
  return <View style={styles.sectionHeading}>
    <View style={styles.sectionHeadingText}>
      <View style={styles.sectionTitleRow}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: palette.textSecondary }]}>{section.title}</Text>
        {hasMeta ? <Text style={[styles.meta, { color: palette.textMuted }]}>
          {section.totalLabel || ''}{section.shownLabel ? ` ${section.shownLabel}` : ''}
        </Text> : null}
      </View>
      {section.tip?.text ? <Text style={[styles.tip, { color: palette.textMuted }]}>{section.tip.text}</Text> : null}
    </View>
    {section.searchOnline ? <Pressable
      accessibilityRole="link"
      accessibilityLabel={section.searchOnline.label || labels.searchOnline}
      onPress={() => onSearchOnline?.(section.searchOnline)}
      style={styles.linkButton}>
      <Text style={[styles.link, { color: palette.link }]}>{section.searchOnline.label || labels.searchOnline}</Text>
    </Pressable> : null}
  </View>;
}

function SearchSection({
  section,
  palette,
  labels,
  onSearchOnline,
  ...cardProps
}) {
  return <View style={styles.section}>
    <SectionHeading section={section} palette={palette} labels={labels} onSearchOnline={onSearchOnline} />
    {(section.subsections || []).map((subsection, index) => <View key={subsection.key || index} style={styles.subsection}>
      {subsection.title ? <View style={styles.subsectionHeading}>
        <Text role="heading" aria-level={4} style={[styles.subsectionTitle, { color: palette.textSecondary }]}>{subsection.title}</Text>
        {subsection.totalLabel || subsection.shownLabel ? <Text style={[styles.meta, { color: palette.textMuted }]}>
          {subsection.totalLabel || ''}{subsection.shownLabel ? ` ${subsection.shownLabel}` : ''}
        </Text> : null}
      </View> : null}
      <ResultGroup
        items={subsection.items || []}
        layout={subsection.layout || 'grid'}
        palette={palette}
        labels={labels}
        {...cardProps}
      />
    </View>)}
  </View>;
}

function EmptyGlyph({ palette }) {
  return <View aria-hidden style={styles.emptyGlyph}>
    <View style={[styles.emptyGlyphRing, { borderColor: palette.textMuted }]} />
    <View style={[styles.emptyGlyphHandle, { backgroundColor: palette.textMuted }]} />
  </View>;
}

function EmptyState({ empty, palette, labels }) {
  return <View style={[styles.empty, { backgroundColor: palette.surface }]}>
    <View style={[styles.emptyIcon, { backgroundColor: palette.surfaceStrong }]}>
      <EmptyGlyph palette={palette} />
    </View>
    <Text role="heading" aria-level={2} style={[styles.emptyTitle, { color: palette.text }]}>
      {empty?.title || labels.emptyTitle}
    </Text>
    <Text style={[styles.emptyBody, { color: palette.textMuted }]}>{empty?.body || labels.emptyBody}</Text>
    {empty?.extra ? <Text style={[styles.emptyBody, { color: palette.textMuted }]}>{empty.extra}</Text> : null}
  </View>;
}

function Pager({ paging, palette, labels, onPage }) {
  if (!paging || !(paging.totalPages > 1)) return null;
  return <View style={styles.pager}>
    <View style={styles.pagerRow}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.previous}
        accessibilityState={{ disabled: !paging.previous }} disabled={!paging.previous}
        onPress={() => onPage?.(paging.previous)}
        style={[styles.pageButton, {
          backgroundColor: paging.previous ? palette.surface : palette.surfaceMuted,
          opacity: paging.previous ? 1 : 0.55,
        }]}>
        <Text style={[styles.pageArrow, { color: palette.text }]}>‹</Text>
      </Pressable>
      {(paging.pages || []).map((page, index) => page.ellipsis
        ? <Text key={`gap-${index}`} style={[styles.ellipsis, { color: palette.textMuted }]}>…</Text>
        : <Pressable key={page.number} accessibilityRole="button"
          accessibilityLabel={`${page.number}`} accessibilityState={{ selected: page.current }}
          onPress={() => onPage?.(page)}
          style={[styles.pageButton, {
            backgroundColor: page.current ? palette.accent : palette.surface,
          }]}>
          <Text style={[styles.pageNumber, { color: page.current ? palette.accentText : palette.text }]}>{page.number}</Text>
        </Pressable>)}
      <Pressable accessibilityRole="button" accessibilityLabel={labels.next}
        accessibilityState={{ disabled: !paging.next }} disabled={!paging.next}
        onPress={() => onPage?.(paging.next)}
        style={[styles.pageButton, {
          backgroundColor: paging.next ? palette.surface : palette.surfaceMuted,
          opacity: paging.next ? 1 : 0.55,
        }]}>
        <Text style={[styles.pageArrow, { color: palette.text }]}>›</Text>
      </Pressable>
    </View>
    {paging.summary ? <Text style={[styles.pageSummary, { color: palette.textMuted }]}>{paging.summary}</Text> : null}
  </View>;
}

function ScrollPills({ scope, palette, onSelectScope }) {
  if (!scope?.options?.length) return null;
  return <View style={styles.scope}>
    {scope.label ? <Text style={[styles.scopeLabel, { color: palette.textMuted }]}>{scope.label}</Text> : null}
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.pills}>
      {scope.options.map(option => <Pressable key={option.value}
        accessibilityRole="button" accessibilityLabel={option.label}
        accessibilityState={{ selected: !!option.active }}
        onPress={() => onSelectScope?.(option)}
        style={[styles.pill, {
          backgroundColor: option.active ? palette.accent : palette.surfaceStrong,
          borderColor: option.active ? palette.accent : palette.border,
        }]}>
        <Text style={[styles.pillText, { color: option.active ? palette.accentText : palette.textSecondary }]}>{option.label}</Text>
      </Pressable>)}
    </ScrollView>
  </View>;
}

function LayoutToggle({ options, palette, onSelectLayout }) {
  if (!options?.length) return null;
  return <View style={[styles.layoutToggle, { borderColor: palette.border }]}>
    {options.map(option => <Pressable key={option.value}
      accessibilityRole="button" accessibilityLabel={option.label}
      accessibilityState={{ selected: !!option.active }}
      onPress={() => onSelectLayout?.(option)}
      style={[styles.layoutButton, {
        backgroundColor: option.active ? palette.accent : palette.surfaceStrong,
      }]}>
      <Text style={[styles.layoutGlyph, { color: option.active ? palette.accentText : palette.textSecondary }]}>
        {option.glyph || option.label}
      </Text>
    </Pressable>)}
  </View>;
}

function ParentPickerPanel({ parentPicker, palette, labels, onSelectParent }) {
  if (!parentPicker) return null;
  return <ParentPicker
    title={parentPicker.title || labels.parentTitle}
    description={parentPicker.description}
    query={parentPicker.query}
    placeholder={parentPicker.placeholder}
    results={parentPicker.results || []}
    selectedId={parentPicker.selectedId}
    state={parentPicker.state || 'ready'}
    labels={{
      placeholder: parentPicker.placeholder || labels.parentPlaceholder,
      empty: parentPicker.emptyLabel || labels.parentEmpty,
      loading: labels.parentLoading,
      errorTitle: labels.parentErrorTitle,
      errorBody: labels.parentErrorBody,
      retry: labels.retry,
      selected: labels.parentSelected,
    }}
    palette={palette}
    onQueryChange={parentPicker.onQueryChange}
    onSelect={onSelectParent}
    onRetry={parentPicker.onRetry}
  />;
}

export function SearchResults({
  title,
  state = 'ready',
  labels = {},
  palette: paletteOverrides,
  scope,
  layoutOptions,
  notes = [],
  sections = [],
  paging,
  empty,
  hasMore = false,
  loadingMore = false,
  parentPicker,
  onSelectScope,
  onSelectLayout,
  onSearchOnline,
  onOpenResult,
  onOpenLink,
  onAction,
  onReorder,
  onRate,
  onPage,
  onLoadMore,
  onRetry,
  onSelectParent,
  renderRating,
  renderActionIcon,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, ...labels };
  return <View style={styles.wrapper} testID={testID}>
    <View style={styles.header}>
      <Text role="heading" aria-level={1} style={[styles.title, { color: palette.text }]}>{title || copy.title}</Text>
      <View style={styles.controls}>
        <ScrollPills scope={scope} palette={palette} onSelectScope={onSelectScope} />
        <LayoutToggle options={layoutOptions} palette={palette} onSelectLayout={onSelectLayout} />
      </View>
    </View>
    {notes.map((note, index) => <Text key={index} style={[styles.note, { color: palette.textMuted }]}>{note}</Text>)}
    {state === 'loading' ? <View style={styles.state}>
      <Spinner size={20} color={palette.accent} />
      <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.loading}</Text>
    </View> : null}
    {state === 'error' ? <View style={styles.state}>
      <Text role="heading" aria-level={2} style={[styles.stateTitle, { color: palette.text }]}>{copy.errorTitle}</Text>
      <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.errorBody}</Text>
      <Pressable accessibilityRole="button" onPress={onRetry}
        style={[styles.retry, { backgroundColor: palette.accent }]}>
        <Text style={[styles.retryText, { color: palette.accentText }]}>{copy.retry}</Text>
      </Pressable>
    </View> : null}
    {state === 'empty' ? <EmptyState empty={empty} palette={palette} labels={copy} /> : null}
    {state === 'ready' ? <View style={styles.sections}>
      {sections.map((section, index) => <SearchSection
        key={section.key || index}
        section={section}
        palette={palette}
        labels={copy}
        onSearchOnline={onSearchOnline}
        onOpenResult={onOpenResult}
        onOpenLink={onOpenLink}
        onAction={onAction}
        onReorder={onReorder}
        onRate={onRate}
        renderRating={renderRating}
        renderActionIcon={renderActionIcon}
      />)}
      {!sections.length ? <EmptyState empty={empty} palette={palette} labels={copy} /> : null}
    </View> : null}
    <Pager paging={paging} palette={palette} labels={copy} onPage={onPage} />
    {hasMore && onLoadMore ? <Pressable accessibilityRole="button"
      accessibilityState={{ busy: loadingMore }} disabled={loadingMore}
      onPress={onLoadMore}
      style={[styles.loadMore, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
      <Text style={[styles.loadMoreText, { color: palette.text }]}>{loadingMore ? copy.loadingMore : copy.loadMore}</Text>
    </Pressable> : null}
    <ParentPickerPanel parentPicker={parentPicker} palette={palette} labels={copy} onSelectParent={onSelectParent} />
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { gap: 16 },
  header: { gap: 12 },
  title: { fontSize: 24, fontWeight: '700', lineHeight: 30 },
  controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  scope: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, flexShrink: 1, minWidth: 0 },
  scopeLabel: { fontSize: 13 },
  pills: { flexDirection: 'row', gap: 8, paddingRight: 4 },
  pill: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 6 },
  pillText: { fontSize: 13, fontWeight: '600' },
  layoutToggle: { flexDirection: 'row', overflow: 'hidden', borderWidth: 1, borderRadius: 6 },
  layoutButton: { width: 36, height: 34, alignItems: 'center', justifyContent: 'center' },
  layoutGlyph: { fontSize: 16, lineHeight: 18 },
  note: { fontSize: 13, lineHeight: 18 },
  sections: { gap: 28 },
  section: { gap: 12 },
  sectionHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  sectionHeadingText: { flex: 1, minWidth: 0, gap: 3 },
  sectionTitleRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', gap: 8 },
  sectionTitle: { fontSize: 17, fontWeight: '600', lineHeight: 22 },
  meta: { fontSize: 13, lineHeight: 18 },
  tip: { fontSize: 13, lineHeight: 18 },
  linkButton: { paddingVertical: 2 },
  link: { fontSize: 13, fontWeight: '600' },
  subsection: { gap: 10 },
  subsectionHeading: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  subsectionTitle: { fontSize: 15, fontWeight: '600', lineHeight: 20 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  list: { gap: 12 },
  listRow: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  state: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 56, paddingHorizontal: 16 },
  stateTitle: { fontSize: 19, fontWeight: '600' },
  stateText: { fontSize: 13, textAlign: 'center' },
  retry: { borderRadius: 6, paddingHorizontal: 14, paddingVertical: 8, marginTop: 4 },
  retryText: { fontSize: 13, fontWeight: '600' },
  empty: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 56, paddingHorizontal: 16, borderRadius: 10 },
  emptyIcon: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
  emptyGlyph: { width: 30, height: 30 },
  emptyGlyphRing: { width: 21, height: 21, borderRadius: 11, borderWidth: 2 },
  emptyGlyphHandle: { position: 'absolute', right: 2, bottom: 3, width: 11, height: 2, transform: [{ rotate: '45deg' }] },
  emptyTitle: { fontSize: 19, fontWeight: '600' },
  emptyBody: { fontSize: 13, lineHeight: 19, textAlign: 'center', maxWidth: 440 },
  pager: { alignItems: 'center', gap: 6, marginTop: 8 },
  pagerRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 6 },
  pageButton: { minWidth: 36, height: 36, borderRadius: 6, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  pageArrow: { fontSize: 20, lineHeight: 22 },
  pageNumber: { fontSize: 13, fontWeight: '600' },
  ellipsis: { fontSize: 15, width: 24, textAlign: 'center' },
  pageSummary: { fontSize: 13 },
  loadMore: { alignSelf: 'center', borderWidth: 1, borderRadius: 6, paddingHorizontal: 18, paddingVertical: 10 },
  loadMoreText: { fontSize: 13, fontWeight: '600' },
});
