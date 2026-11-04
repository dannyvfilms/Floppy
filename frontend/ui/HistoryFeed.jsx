import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { DateTimePicker } from './DateTimePicker';
import { MediaCardView } from './MediaCardView';

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
  link: '#818cf8',
  danger: '#ef4444',
  warning: '#f59e0b',
  success: '#10b981',
  radius: 8,
  radiusSmall: 6,
  mediaCard: {
    card: '#27272a',
    text: '#fafafa',
    textSecondary: '#d4d4d8',
    textMuted: '#a1a1aa',
    border: '#3f3f46',
    link: '#818cf8',
    star: '#facc15',
    chipBackground: 'rgba(24, 24, 27, 0.92)',
    chipText: '#ffffff',
    placeholder: '#3f3f46',
    progressTrack: 'rgba(24, 24, 27, 0.6)',
    progressFill: '#6366f1',
    progressPaused: 'rgba(99, 102, 241, 0.4)',
  },
};

const DEFAULT_LABELS = {
  history: 'History',
  previousYear: 'Go back one year',
  previousMonth: 'Go to previous month',
  nextMonth: 'Go to next month',
  currentMonth: 'Go to current month',
  filters: 'Filter history',
  hideFilters: 'Hide filters',
  clearFilters: 'Clear filters',
  saveView: 'Save view',
  apply: 'Apply',
  allTypes: 'All types',
  mediaType: 'Media type',
  viewMode: 'View mode',
  activity: 'Activity (watched)',
  release: 'Release dates',
  genre: 'Genre',
  allGenres: 'All genres',
  impliedGenre: 'Implied genre',
  allImpliedGenres: 'All implied genres',
  from: 'From',
  to: 'To',
  dateRange: 'Date range',
  refreshing: 'Refreshing history in background...',
  dismiss: 'Dismiss refresh notice',
  loadMore: 'Load more',
  loadDay: 'Load this day',
  loadingDay: 'Loading this day...',
  noHistory: 'No watch history yet',
  noHistoryCopy: 'Start tracking movies and episodes to see them here.',
  loadError: 'History could not be loaded.',
  retry: 'Try again',
  loading: 'Loading history...',
  edit: 'Edit',
  delete: 'Delete',
  showMore: 'Show more',
  showLess: 'Show less',
  status: 'Status',
  rate: 'Rate',
  close: 'Close',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  open: 'Open',
  items: 'items',
  item: 'item',
  releases: 'releases',
  release: 'release',
  activeDays: 'Active days',
  entries: 'Activity entries',
  trackedTime: 'Tracked time',
  averagePerDay: 'Average per active day',
  averageGap: 'Average gap',
  longestStreak: 'Longest streak',
  mostActiveWeekday: 'Most active weekday',
  previousPage: 'Previous page',
  nextPage: 'Next page',
  page: 'Page',
  clear: 'Clear',
};

const DEFAULT_MEDIA_TYPES = [
  { value: 'tv', label: 'TV Show' },
  { value: 'movie', label: 'Movie' },
  { value: 'anime', label: 'Anime' },
  { value: 'game', label: 'Game' },
  { value: 'music', label: 'Music' },
  { value: 'book', label: 'Book' },
  { value: 'manga', label: 'Manga' },
  { value: 'comic', label: 'Comic' },
  { value: 'podcast', label: 'Podcast' },
  { value: 'video', label: 'Video' },
  { value: 'boardgame', label: 'Board Game' },
];

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function mergePalette(palette) {
  return {
    ...DEFAULT_PALETTE,
    ...(palette || {}),
    mediaCard: { ...DEFAULT_PALETTE.mediaCard, ...(palette?.mediaCard || {}) },
  };
}

function buttonPalette(palette) {
  return {
    radius: palette.radiusSmall,
    primary: {
      background: palette.accentStrong,
      pressed: palette.accentStrong,
      hovered: palette.accent,
      text: palette.accentContrast,
      border: 'transparent',
    },
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    'ghost-danger': {
      background: 'transparent',
      pressed: palette.danger,
      hovered: palette.danger,
      text: palette.danger,
      border: 'transparent',
    },
    focusStyle: {},
  };
}

function chipPalette(palette) {
  return {
    indigo: {
      color: palette.accentContrast,
      backgroundColor: palette.accentStrong,
    },
    outline: {
      color: palette.textSecondary,
      borderColor: palette.border,
      borderWidth: 1,
    },
  };
}

function dateTimePalette(palette) {
  return {
    text: palette.text,
    textSecondary: palette.textSecondary,
    textMuted: palette.textMuted,
    surface: palette.surface,
    surfaceStrong: palette.surfaceStrong,
    surfaceMuted: palette.surfaceMuted,
    border: palette.border,
    accent: palette.accent,
    accentContrast: palette.accentContrast,
    link: palette.link,
    danger: palette.danger,
    radius: palette.radius,
    radiusSmall: palette.radiusSmall,
    fontSize: 14,
    smallFontSize: 12,
  };
}

function mediaTypeLabel(options, value) {
  const match = (options || []).find(item => item.value === value);
  return match ? match.label : value;
}

function truncatedNote(note, expanded) {
  if (!note) return '';
  return expanded || note.length <= 140 ? note : `${note.slice(0, 140).trimEnd()}…`;
}

function rowModel(entry, labels) {
  const parts = [];
  if (entry.verb) parts.push({ text: entry.verb, link: true });
  if (entry.when) parts.push({ text: `${parts.length ? ' · ' : ''}${entry.when}`, muted: true });
  if (entry.runtime) parts.push({ text: ` · ${entry.runtime}`, muted: true });
  const lines = parts.length ? [{ join: 'plain', parts }] : [];
  return {
    layout: 'row',
    mediaType: entry.mediaType,
    href: entry.href || '',
    image: entry.image || { src: null, fallback: '', source: 'primary' },
    title: entry.title,
    altTitle: entry.altTitle || null,
    matched: entry.subtitle ? { text: entry.subtitle, title: entry.subtitle } : null,
    titleLinks: [],
    cornerChips: [],
    progressBar: null,
    scoreText: entry.score == null ? null : String(entry.score),
    lines,
    actions: null,
  };
}

export function HistoryDaySummary({ day, mode = 'activity', labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const count = day.entryCount ?? day.entries?.length ?? 0;
  let text;
  if (mode === 'release') {
    text = `${day.releaseCount ?? count} ${day.releaseCount === 1 ? copy.release : copy.releases}`;
  } else {
    const noun = count === 1 ? copy.item : copy.items;
    text = `${count} ${noun}${day.runtimeLabel ? ` · ${day.runtimeLabel}` : ''}`;
  }
  return <Text accessibilityLabel={text} style={[styles.daySummary, { color: colors.textMuted }]}>{text}</Text>;
}

export function HistoryEntryRow({
  entry,
  labels,
  palette,
  first = false,
  onOpen,
  onEdit,
  onDelete,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const [noteOpen, setNoteOpen] = useState(false);
  const note = entry.note || '';
  const longNote = note.length > 140;
  return <View style={[styles.entry, !first && { borderTopWidth: 1, borderTopColor: colors.border }]}>
    <MediaCardView
      model={rowModel(entry, copy)}
      labels={copy}
      palette={colors.mediaCard}
      width={240}
      onOpen={onOpen ? () => onOpen(entry) : undefined} />
    {note ? <View style={styles.noteWrap}>
      <Text style={[styles.note, { color: colors.textSecondary }]}>{truncatedNote(note, noteOpen)}</Text>
      {longNote ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: noteOpen }}
        onPress={() => setNoteOpen(current => !current)} style={styles.noteToggle}>
        <Text style={[styles.noteToggleText, { color: colors.link }]}>{noteOpen ? copy.showLess : copy.showMore}</Text>
      </Pressable> : null}
    </View> : null}
    {entry.canEdit || entry.canDelete ? <View style={styles.entryActions}>
      {entry.canEdit ? <Button label={copy.edit} size="sm" onPress={() => onEdit?.(entry)} palette={buttonPalette(colors)} /> : null}
      {entry.canDelete ? <Button label={copy.delete} size="sm" tone="ghost-danger" onPress={() => onDelete?.(entry)} palette={buttonPalette(colors)} /> : null}
    </View> : null}
  </View>;
}

export function HistoryDayGroup({
  day,
  mode = 'activity',
  labels,
  palette,
  onOpenEntry,
  onEditEntry,
  onDeleteEntry,
  onLoadMore,
  onLoadDay,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const entries = day.entries || [];
  return <View style={styles.dayGroup}>
    <View style={[styles.dayHeader, { borderBottomColor: colors.border }]}>
      <View style={styles.dayDate}>
        {day.weekday ? <Text style={[styles.weekday, { color: colors.text }]}>{day.weekday}</Text> : null}
        <Text style={[styles.dateLabel, { color: colors.text }, !day.weekday && styles.dateLabelOnly]}>{day.dateLabel}</Text>
      </View>
      <HistoryDaySummary day={day} mode={mode} labels={copy} palette={colors} />
    </View>
    {day.lazy ? <View style={[styles.lazyDay, { borderColor: colors.border }]}>
      <Text style={[styles.lazyText, { color: colors.textMuted }]}>{copy.loadingDay}</Text>
      <Button label={copy.loadDay} size="sm" tone="surface" palette={buttonPalette(colors)}
        onPress={() => onLoadDay?.(day)} />
    </View> : <>
      {entries.map((entry, index) => <HistoryEntryRow key={entry.key} entry={entry} labels={copy}
        palette={colors} first={index === 0} onOpen={onOpenEntry} onEdit={onEditEntry}
        onDelete={onDeleteEntry} />)}
      {day.hasMore ? <View style={styles.loadMore}>
        <Button label={day.remaining ? `${copy.loadMore} (${day.remaining})` : copy.loadMore}
          size="sm" tone="surface" palette={buttonPalette(colors)} onPress={() => onLoadMore?.(day)} />
      </View> : null}
    </>}
  </View>;
}

export function HistoryActivitySummary({ stats, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  if (!stats?.length) return null;
  return <View style={[styles.summary, { borderColor: colors.border, backgroundColor: colors.surface }]}>
    {stats.map(stat => <View key={stat.label} style={styles.summaryItem}>
      <Text style={[styles.summaryValue, { color: colors.text }]}>{stat.value}</Text>
      <Text style={[styles.summaryLabel, { color: colors.textMuted }]}>{stat.label}</Text>
    </View>)}
  </View>;
}

export function HistoryFilterPanel({
  filters = {},
  options = {},
  labels,
  palette,
  onApply,
  onClear,
  onSaveView,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const [state, setState] = useState({
    from: filters.from || '',
    to: filters.to || '',
    mediaTypes: [...(filters.mediaTypes || [])],
    genre: filters.genre || '',
    impliedGenre: filters.impliedGenre || '',
    mode: filters.mode || 'activity',
  });
  const mediaTypes = options.mediaTypes?.length ? options.mediaTypes : DEFAULT_MEDIA_TYPES;

  useEffect(() => {
    setState({
      from: filters.from || '',
      to: filters.to || '',
      mediaTypes: [...(filters.mediaTypes || [])],
      genre: filters.genre || '',
      impliedGenre: filters.impliedGenre || '',
      mode: filters.mode || 'activity',
    });
  }, [filters.from, filters.to, filters.mode, filters.genre, filters.impliedGenre, JSON.stringify(filters.mediaTypes || [])]);

  function toggleMediaType(value) {
    setState(current => ({
      ...current,
      mediaTypes: current.mediaTypes.includes(value)
        ? current.mediaTypes.filter(item => item !== value)
        : [...current.mediaTypes, value],
    }));
  }

  const chip = (label, selected, onPress, key) => <Badge key={key} label={label} size="sm"
    tone={selected ? 'indigo' : 'outline'} palette={chipPalette(colors)} onPress={onPress}
    accessibilityLabel={label} />;

  return <View style={[styles.filterPanel, { borderColor: colors.border, backgroundColor: colors.surface }]}>
    <Text style={[styles.filterHeading, { color: colors.text }]}>{copy.dateRange}</Text>
    <View style={styles.rangeRow}>
      <View style={styles.rangeField}>
        <Text style={[styles.filterLabel, { color: colors.textMuted }]}>{copy.from}</Text>
        <DateTimePicker value={state.from} trackTime={false} labels={{ field: copy.from }}
          palette={dateTimePalette(colors)}
          onChange={next => setState(current => ({ ...current, from: next }))} />
      </View>
      <View style={styles.rangeField}>
        <Text style={[styles.filterLabel, { color: colors.textMuted }]}>{copy.to}</Text>
        <DateTimePicker value={state.to} trackTime={false} labels={{ field: copy.to }}
          palette={dateTimePalette(colors)}
          onChange={next => setState(current => ({ ...current, to: next }))} />
      </View>
    </View>
    <Text style={[styles.filterHeading, { color: colors.text }]}>{copy.mediaType}</Text>
    <View style={styles.chipRow}>
      {mediaTypes.map(item => chip(item.label, state.mediaTypes.includes(item.value),
        () => toggleMediaType(item.value), item.value))}
    </View>
    <Text style={[styles.filterHeading, { color: colors.text }]}>{copy.viewMode}</Text>
    <View style={styles.chipRow}>
      {chip(copy.activity, state.mode === 'activity', () => setState(current => ({ ...current, mode: 'activity' })), 'activity')}
      {chip(copy.release, state.mode === 'release', () => setState(current => ({ ...current, mode: 'release' })), 'release')}
    </View>
    {options.genres?.length ? <>
      <Text style={[styles.filterHeading, { color: colors.text }]}>{copy.genre}</Text>
      <View style={styles.chipRow}>
        {options.genres.map(genre => chip(genre, state.genre === genre,
          () => setState(current => ({ ...current, genre: current.genre === genre ? '' : genre })), `genre-${genre}`))}
      </View>
    </> : null}
    {options.impliedGenres?.length ? <>
      <Text style={[styles.filterHeading, { color: colors.text }]}>{copy.impliedGenre}</Text>
      <View style={styles.chipRow}>
        {options.impliedGenres.map(genre => chip(genre, state.impliedGenre === genre,
          () => setState(current => ({ ...current, impliedGenre: current.impliedGenre === genre ? '' : genre })), `implied-${genre}`))}
      </View>
    </> : null}
    <View style={styles.filterActions}>
      <Button label={copy.clearFilters} size="sm" tone="surface" palette={buttonPalette(colors)}
        onPress={() => { onClear?.(); }} />
      <Button label={copy.saveView} size="sm" tone="surface" palette={buttonPalette(colors)}
        onPress={() => { onSaveView?.(state); }} />
      <Button label={copy.apply} size="sm" palette={buttonPalette(colors)}
        onPress={() => { onApply?.(state); }} />
    </View>
  </View>;
}

export function HistoryState({ kind = 'empty', labels, palette, onRetry, onPress }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const content = {
    loading: { glyph: '◷', title: copy.loading, copy: '' },
    empty: { glyph: '◷', title: copy.noHistory, copy: copy.noHistoryCopy },
    error: { glyph: '!', title: copy.loadError, copy: '' },
  }[kind] || { glyph: '◷', title: copy.noHistory, copy: copy.noHistoryCopy };
  const retry = kind === 'error' ? onRetry : onPress;
  return <View style={[styles.state, { backgroundColor: colors.surface }]}>
    <View style={[styles.stateGlyph, { backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.stateGlyphText, { color: colors.textMuted }]}>{content.glyph}</Text>
    </View>
    <Text style={[styles.stateTitle, { color: colors.text }]}>{content.title}</Text>
    {content.copy ? <Text style={[styles.stateCopy, { color: colors.textMuted }]}>{content.copy}</Text> : null}
    {retry ? <View style={styles.stateAction}>
      <Button label={kind === 'error' ? copy.retry : copy.open} size="sm" tone="surface"
        palette={buttonPalette(colors)} onPress={retry} />
    </View> : null}
  </View>;
}

export function HistoryFeed({
  model = {},
  labels,
  palette,
  onNavigate,
  onLoadMore,
  onLoadDay,
  onOpenEntry,
  onEditEntry,
  onDeleteEntry,
  onApplyFilters,
  onClearFilters,
  onSaveView,
  onRetry,
  onDismissRefresh,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [refreshDismissed, setRefreshDismissed] = useState(false);
  const mode = model.mode || 'activity';
  const days = model.days || [];
  const nav = model.nav || {};
  const filters = model.filters || {};
  const options = model.options || {};
  const activeCount = filters.activeCount ?? 0;
  const showRefresh = model.refreshing && !refreshDismissed;

  return <View style={styles.feed}>
    {showRefresh ? <View style={[styles.refresh, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.refreshText, { color: colors.text }]}>{copy.refreshing}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.dismiss}
        onPress={() => { setRefreshDismissed(true); onDismissRefresh?.(); }}>
        <Text style={[styles.refreshClose, { color: colors.textMuted }]}>✕</Text>
      </Pressable>
    </View> : null}

    {nav.monthLabel ? <View style={styles.monthNav}>
      <View style={styles.monthNavSide}>
        {nav.previousYear ? <Button label={nav.previousYear.label || copy.previousYear} size="sm" tone="surface"
          palette={buttonPalette(colors)} disabled={nav.previousYear.disabled}
          onPress={() => onNavigate?.({ kind: 'year', direction: -1, url: nav.previousYear.url })} /> : null}
        {nav.previousMonth ? <Button label={nav.previousMonth.label || copy.previousMonth} size="sm" tone="surface"
          palette={buttonPalette(colors)} disabled={nav.previousMonth.disabled}
          onPress={() => onNavigate?.({ kind: 'month', direction: -1, url: nav.previousMonth.url })} /> : null}
      </View>
      <Text accessibilityRole="header" style={[styles.monthLabel, { color: colors.text }]}>{nav.monthLabel}</Text>
      <View style={styles.monthNavSide}>
        {nav.nextMonth ? <Button label={nav.nextMonth.label || copy.nextMonth} size="sm" tone="surface"
          palette={buttonPalette(colors)} disabled={nav.nextMonth.disabled}
          onPress={() => onNavigate?.({ kind: 'month', direction: 1, url: nav.nextMonth.url })} /> : null}
        {nav.currentMonth ? <Button label={nav.currentMonth.label || copy.currentMonth} size="sm" tone="surface"
          palette={buttonPalette(colors)} disabled={nav.currentMonth.disabled}
          onPress={() => onNavigate?.({ kind: 'current', url: nav.currentMonth.url })} /> : null}
      </View>
    </View> : null}

    <View style={styles.toolbar}>
      <Button label={filtersOpen ? copy.hideFilters : copy.filters} size="sm" tone="surface"
        palette={buttonPalette(colors)} onPress={() => setFiltersOpen(current => !current)} />
      {activeCount > 0 ? <Badge label={String(activeCount)} size="sm" tone="indigo"
        palette={chipPalette(colors)} accessibilityLabel={`${copy.filters}: ${activeCount}`} /> : null}
      <Badge label={mode === 'release' ? copy.release : copy.activity} size="sm" tone="outline"
        palette={chipPalette(colors)} />
      {filters.rangeLabel ? <Text style={[styles.toolbarText, { color: colors.textMuted }]}>{filters.rangeLabel}</Text> : null}
      {filters.mediaTypes?.length ? <Text style={[styles.toolbarText, { color: colors.textMuted }]}>
        {filters.mediaTypes.map(value => mediaTypeLabel(options.mediaTypes, value)).join(', ')}
      </Text> : null}
    </View>

    {filtersOpen ? <HistoryFilterPanel filters={filters} options={options} labels={copy}
      palette={colors} onApply={onApplyFilters} onClear={onClearFilters} onSaveView={onSaveView} /> : null}

    {model.summary?.length ? <HistoryActivitySummary stats={model.summary} labels={copy} palette={colors} /> : null}

    {model.error ? <HistoryState kind="error" labels={copy} palette={colors} onRetry={onRetry} /> : null}
    {!model.error && model.loading && !days.length
      ? <HistoryState kind="loading" labels={copy} palette={colors} />
      : null}
    {!model.error && !model.loading && !days.length
      ? <HistoryState kind="empty" labels={copy} palette={colors} onPress={onRetry} />
      : null}

    {days.map(day => <HistoryDayGroup key={day.key} day={day} mode={mode} labels={copy}
      palette={colors} onOpenEntry={onOpenEntry} onEditEntry={onEditEntry}
      onDeleteEntry={onDeleteEntry} onLoadMore={onLoadMore} onLoadDay={onLoadDay} />)}

    {model.pagination && model.pagination.pageCount > 1 ? <View style={styles.pagination}>
      <Button label={copy.previousPage} size="sm" tone="surface" palette={buttonPalette(colors)}
        disabled={!model.pagination.previousUrl}
        onPress={() => onNavigate?.({ kind: 'page', direction: -1, url: model.pagination.previousUrl })} />
      <Text style={[styles.pageLabel, { color: colors.textMuted }]}>
        {`${copy.page} ${model.pagination.page} / ${model.pagination.pageCount}`}
      </Text>
      <Button label={copy.nextPage} size="sm" tone="surface" palette={buttonPalette(colors)}
        disabled={!model.pagination.nextUrl}
        onPress={() => onNavigate?.({ kind: 'page', direction: 1, url: model.pagination.nextUrl })} />
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  feed: { gap: 16 },
  refresh: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  refreshText: { flex: 1, fontSize: 13, fontWeight: '500' },
  refreshClose: { fontSize: 14, fontWeight: '700' },
  monthNav: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  monthNavSide: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  monthLabel: { flex: 1, textAlign: 'center', fontSize: 18, fontWeight: '600' },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  toolbarText: { fontSize: 12 },
  filterPanel: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  filterHeading: { fontSize: 13, fontWeight: '600' },
  filterLabel: { fontSize: 11, marginBottom: 2 },
  rangeRow: { flexDirection: 'row', gap: 12 },
  rangeField: { flex: 1, minWidth: 0 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  filterActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  summary: { flexDirection: 'row', flexWrap: 'wrap', borderWidth: 1, borderRadius: 8, padding: 12, gap: 12 },
  summaryItem: { minWidth: 96, flexGrow: 1 },
  summaryValue: { fontSize: 16, fontWeight: '600' },
  summaryLabel: { fontSize: 11, marginTop: 2 },
  dayGroup: { gap: 8 },
  dayHeader: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, borderBottomWidth: 1, paddingBottom: 8 },
  dayDate: { flexDirection: 'row', alignItems: 'baseline', gap: 6, flexWrap: 'wrap', flex: 1 },
  weekday: { fontSize: 18, fontWeight: '600' },
  dateLabel: { fontSize: 18 },
  dateLabelOnly: { fontWeight: '600' },
  daySummary: { fontSize: 12 },
  entry: { paddingVertical: 6 },
  noteWrap: { paddingHorizontal: 12, gap: 2 },
  note: { fontSize: 12, lineHeight: 18 },
  noteToggle: { alignSelf: 'flex-start', paddingVertical: 2 },
  noteToggleText: { fontSize: 12, fontWeight: '600' },
  entryActions: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, paddingTop: 4 },
  lazyDay: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, alignItems: 'center', gap: 8, paddingVertical: 20 },
  lazyText: { fontSize: 12 },
  loadMore: { alignItems: 'center', paddingTop: 4 },
  state: { borderRadius: 8, alignItems: 'center', paddingVertical: 32, paddingHorizontal: 16, gap: 6 },
  stateGlyph: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', marginBottom: 4 },
  stateGlyphText: { fontSize: 20, fontWeight: '700' },
  stateTitle: { fontSize: 16, fontWeight: '600' },
  stateCopy: { fontSize: 12, textAlign: 'center' },
  stateAction: { marginTop: 6 },
  pagination: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12, paddingTop: 4 },
  pageLabel: { fontSize: 12 },
});
