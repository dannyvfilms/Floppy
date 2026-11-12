import { Modal } from './Modal';
import React from 'react';
import {
  Image,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { MediaCardActionHost } from './MediaCardActionHost';
import { MediaCard } from './MediaCard';
import { FormError, FormSelect, FormStatus, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
  background: '#18181b',
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
  danger: '#ef4444',
  success: '#10b981',
  card: '#27272a',
  link: '#818cf8',
  star: '#facc15',
  placeholder: '#3f3f46',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  addTitle: 'Add an Item',
  recommendTitle: 'Recommend an Item',
  addSubtitle: 'Search for media to add directly to this list.',
  recommendSubtitle: 'Search for media to recommend adding to this list.',
  close: 'Close search',
  search: 'Search',
  searchMovie: 'Search movies...',
  searchShow: 'Search shows...',
  searchBook: 'Search books...',
  searchGame: 'Search games...',
  searchAnime: 'Search anime...',
  mediaType: 'Media type',
  idle: 'Search for media above to get started',
  short: 'Keep typing. Enter at least 2 characters.',
  loading: 'Searching the providers…',
  error: 'The search could not load. Please try again in a moment.',
  noResults: 'No results found for',
  tryDifferent: 'Try a different search term',
  page: 'Showing page',
  of: 'of',
  previous: 'Previous page',
  next: 'Next page',
  add: 'Add to List',
  recommend: 'Recommend Item',
  alreadyInList: 'Already in this list',
  alreadyRecommended: 'Already recommended for this list',
  details: 'Details',
  synopsis: 'Synopsis',
  noSynopsis: 'No synopsis is available.',
  score: 'Score',
  year: 'Year',
  status: 'Status',
  format: 'Format',
  episodes: 'Episodes',
  seasons: 'Seasons',
  runtime: 'Runtime',
  pages: 'Pages',
  chapters: 'Chapters',
  studios: 'Studio',
  permission: 'You do not have permission to use this flow for this list.',
  smart: 'Smart lists update from their rules and do not support manual additions.',
  back: 'Back',
  closePreview: 'Close details',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function badgePalette(colors) {
  return {
    outline: { color: colors.textSecondary, borderColor: colors.border, borderWidth: 1 },
    indigo: { color: colors.accentText, backgroundColor: colors.accentStrong },
    violet: { color: '#e9d5ff', backgroundColor: 'rgba(139, 92, 246, 0.25)', borderColor: 'rgba(167, 139, 250, 0.4)', borderWidth: 1 },
    success: { color: colors.success },
    danger: { color: colors.danger },
  };
}

export function ListItemSearch({
  mode = 'add',
  listName = '',
  query = '',
  mediaType,
  mediaTypes = [],
  results = [],
  status = 'idle',
  error,
  page = 1,
  totalPages = 1,
  labels: suppliedLabels,
  palette,
  onQueryChange,
  onMediaTypeChange,
  onPage,
  onSelectResult,
  onClose,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(suppliedLabels);
  const { width } = useWindowDimensions();
  const columns = width >= 920 ? 5 : width >= 720 ? 4 : width >= 520 ? 3 : 2;
  const cardWidth = Math.min(170, Math.max(120, (width - 64 - (columns - 1) * 12) / columns));
  const placeholders = {
    movie: copy.searchMovie,
    tv: copy.searchShow,
    book: copy.searchBook,
    game: copy.searchGame,
    anime: copy.searchAnime,
  };
  const placeholder = placeholders[mediaType] || copy.searchMovie;
  const isRecommend = mode === 'recommend';

  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: colors.background }]}>
      <View style={styles.screen}>
        <View style={styles.header}>
          <View style={styles.headingCopy}>
            <Text role="heading" aria-level={1} style={[styles.title, { color: colors.text }]}>
              {isRecommend ? copy.recommendTitle : copy.addTitle}
            </Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>{listName}</Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>
              {isRecommend ? copy.recommendSubtitle : copy.addSubtitle}
            </Text>
          </View>
          <Button label={copy.close} tone="surface" onPress={onClose} palette={colors} />
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.body}>
          <View style={styles.controls}>
            <View style={styles.searchField}>
              <FormTextField label={copy.search} value={query} placeholder={placeholder}
                onChangeText={onQueryChange} palette={colors} />
            </View>
            <View style={styles.typeField}>
              <FormSelect label={copy.mediaType} value={mediaType} options={mediaTypes}
                onChange={onMediaTypeChange} palette={colors} />
            </View>
          </View>

          {status === 'loading' ? <FormStatus message={copy.loading} tone="loading" palette={colors} /> : null}
          {status === 'error' ? <FormError message={error || copy.error} palette={colors} /> : null}
          {status === 'permission' ? <FormError message={error || copy.permission} palette={colors} /> : null}
          {status === 'smart' ? <FormError message={error || copy.smart} palette={colors} /> : null}
          {status === 'short' ? <Text style={[styles.stateText, { color: colors.textMuted }]}>{copy.short}</Text> : null}

          {status === 'ready' && results.length ? <View style={styles.grid}>
            {results.map((result, index) => <View key={result.id || result.title || index} style={{ width: cardWidth }}>
              <MediaCard model={result.media} width={cardWidth} palette={colors}
                onOpen={() => onSelectResult?.(result)} />
            </View>)}
          </View> : null}

          {status === 'ready' && results.length === 0 ? <View style={styles.empty}>
            <Text style={[styles.emptyTitle, { color: colors.text }]}>{copy.noResults}</Text>
            <Text style={[styles.stateText, { color: colors.textMuted }]}>
              {query ? `"${query}"` : ''} · {copy.tryDifferent}
            </Text>
          </View> : null}

          {status === 'idle' ? <View style={styles.empty}>
            <Text style={[styles.stateText, { color: colors.textMuted }]}>{copy.idle}</Text>
          </View> : null}

          {status === 'ready' && totalPages > 1 ? <View style={styles.pager}>
            <Text style={[styles.stateText, { color: colors.textMuted }]}>
              {copy.page} {page} {copy.of} {totalPages}
            </Text>
            <View style={styles.pagerActions}>
              <Button label={copy.previous} tone="surface" disabled={page <= 1}
                onPress={() => onPage?.(page - 1)} palette={colors} />
              <Button label={copy.next} tone="surface" disabled={page >= totalPages}
                onPress={() => onPage?.(page + 1)} palette={colors} />
            </View>
          </View> : null}
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

function DetailRow({ label, value, colors }) {
  if (value == null || value === '') return null;
  return <View style={styles.detailRow}>
    <Text style={[styles.detailLabel, { color: colors.textMuted }]}>{label}</Text>
    <Text style={[styles.detailValue, { color: colors.textSecondary }]}>{String(value)}</Text>
  </View>;
}

export function ListItemPreview({
  open = false,
  mode = 'add',
  media = {},
  status = 'ready',
  error,
  alreadyInList = false,
  alreadyRecommended = false,
  labels: suppliedLabels,
  palette,
  onClose,
  onConfirm,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(suppliedLabels);
  const badges = badgePalette(colors);
  const isRecommend = mode === 'recommend';
  const details = media.details || {};
  const blocked = alreadyInList || alreadyRecommended;
  const actionLabel = isRecommend ? copy.recommend : copy.add;

  return <MediaCardActionHost open={open} action={{ title: `${media.mediaTypeLabel || 'Item'} ${copy.details}` }}
    labels={{ close: copy.closePreview }} palette={colors} onClose={onClose}>
    <ScrollView style={styles.previewScroll} keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.previewBody}>
      {status === 'loading' ? <FormStatus message={copy.loading} tone="loading" palette={colors} /> : null}
      {status === 'error' ? <FormError message={error || copy.error} palette={colors} /> : null}
      {status === 'ready' ? <>
        <View style={styles.previewHeader}>
          <View style={[styles.posterFrame, { backgroundColor: colors.placeholder }]}>
            {media.image?.src ? <Image source={{ uri: media.image.src }} style={StyleSheet.absoluteFill}
              resizeMode="cover" accessible={false} /> : null}
          </View>
          <View style={styles.previewCopy}>
            <Text style={[styles.previewTitle, { color: colors.text }]}>{media.title}</Text>
            <Text style={[styles.stateText, { color: colors.textMuted }]}>{media.mediaTypeLabel}</Text>
            <Text style={[styles.stateText, { color: colors.textMuted }]}>{media.year || ''}</Text>
            {media.score != null ? <View style={styles.scoreRow}>
              <Text style={[styles.scoreStar, { color: colors.star }]}>★</Text>
              <Text style={[styles.previewScore, { color: colors.text }]}>{media.score}</Text>
              <Text style={[styles.stateText, { color: colors.textMuted }]}>/10</Text>
              {media.scoreCount != null ? <Text style={[styles.stateText, { color: colors.textMuted }]}>
                ({media.scoreCount})
              </Text> : null}
            </View> : null}
          </View>
        </View>

        {media.genres?.length ? <View style={styles.chipRow}>
          {media.genres.map(genre => <Badge key={genre} label={genre} tone="violet" palette={badges} />)}
        </View> : null}

        <View style={styles.field}>
          <Text style={[styles.groupLabel, { color: colors.textMuted }]}>{copy.synopsis}</Text>
          <Text style={[styles.synopsis, { color: colors.textSecondary }]}>
            {media.synopsis || copy.noSynopsis}
          </Text>
        </View>

        <View style={[styles.details, { borderColor: colors.border }]}>
          <Text style={[styles.groupLabel, { color: colors.textMuted }]}>{copy.details}</Text>
          <DetailRow label={copy.status} value={details.status} colors={colors} />
          <DetailRow label={copy.format} value={details.format} colors={colors} />
          <DetailRow label={copy.episodes} value={details.episodes} colors={colors} />
          <DetailRow label={copy.seasons} value={details.seasons} colors={colors} />
          <DetailRow label={copy.runtime} value={details.runtime} colors={colors} />
          <DetailRow label={copy.pages} value={details.pages} colors={colors} />
          <DetailRow label={copy.chapters} value={details.chapters} colors={colors} />
          <DetailRow label={copy.studios} value={(details.studios || []).join(', ')} colors={colors} />
        </View>

        {blocked ? <View style={[styles.notice, { backgroundColor: colors.surfaceStrong }]}>
          <Text style={[styles.noticeText, { color: colors.textMuted }]}>
            {alreadyInList ? copy.alreadyInList : copy.alreadyRecommended}
          </Text>
        </View> : <View style={styles.previewActions}>
          <Button label={actionLabel} tone="primary" onPress={onConfirm} palette={colors} />
          <Button label={copy.back} tone="surface" onPress={onClose} palette={colors} />
        </View>}
      </> : null}
    </ScrollView>
  </MediaCardActionHost>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1 },
  screen: { flex: 1, paddingTop: 12 },
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingBottom: 8 },
  headingCopy: { flex: 1, minWidth: 0, gap: 2 },
  title: { fontSize: 24, fontWeight: '700' },
  subtitle: { fontSize: 12, lineHeight: 17 },
  body: { paddingHorizontal: 16, paddingBottom: 32, gap: 14 },
  controls: { gap: 10 },
  searchField: { minWidth: 0 },
  typeField: { minWidth: 0 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  stateText: { fontSize: 13, lineHeight: 18 },
  empty: { alignItems: 'center', gap: 6, paddingVertical: 32 },
  emptyTitle: { fontSize: 16, fontWeight: '600' },
  pager: { alignItems: 'center', gap: 8 },
  pagerActions: { flexDirection: 'row', gap: 8 },
  previewScroll: { flexGrow: 0 },
  previewBody: { gap: 12 },
  previewHeader: { flexDirection: 'row', gap: 12 },
  posterFrame: { width: 84, aspectRatio: 2 / 3, borderRadius: 8, overflow: 'hidden' },
  previewCopy: { flex: 1, minWidth: 0, gap: 2 },
  previewTitle: { fontSize: 17, fontWeight: '700', lineHeight: 22 },
  scoreRow: { flexDirection: 'row', alignItems: 'center', gap: 3, marginTop: 3 },
  scoreStar: { fontSize: 13 },
  previewScore: { fontSize: 14, fontWeight: '700' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  field: { gap: 6 },
  groupLabel: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  synopsis: { fontSize: 13, lineHeight: 19 },
  details: { borderTopWidth: 1, paddingTop: 10, gap: 4 },
  detailRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  detailLabel: { fontSize: 12, minWidth: 70 },
  detailValue: { flexShrink: 1, fontSize: 12 },
  notice: { borderRadius: 8, padding: 10 },
  noticeText: { fontSize: 13, fontWeight: '600', textAlign: 'center' },
  previewActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
