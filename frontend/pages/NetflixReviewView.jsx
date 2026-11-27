import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';

// Shared presentation for the Netflix import review page. The web adapter
// (mountNetflixReview.jsx) supplies the search/record/dismiss transport; the
// server renders the same rows as a no-JavaScript fallback.

const DEFAULT_LABELS = {
  search: 'Search',
  record: 'Record play',
  dismiss: 'Dismiss row',
  season: 'Season',
  episode: 'Episode',
  movie: 'Movie',
  tv: 'TV show',
  titleToSearch: 'Title to search',
  mediaType: 'Media type',
  searchHint: 'Search above, then choose the right title.',
  noResults: 'No results for that title and type. Try the other type or a shorter title.',
  searching: 'Searching',
  searchFailed: 'Search failed. Try again.',
  resolved: 'Recorded as “%(title)s”.',
  resolvedShort: 'Recorded.',
  dismissed: 'Dismissed, no play recorded.',
};

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function buttonPalette(palette) {
  return {
    primary: {
      background: palette.accentStrong,
      pressed: palette.accent,
      hovered: palette.accent,
      text: palette.accentText,
      border: palette.accentStrong,
    },
    surface: {
      background: palette.surface,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    'ghost-danger': {
      background: 'transparent',
      pressed: palette.dangerSoft,
      hovered: palette.dangerSoft,
      text: palette.danger,
      border: 'transparent',
    },
  };
}

function formatDay(value) {
  return value ? String(value).slice(0, 10) : '—';
}

function ResultRow({ result, selected, bordered = true, onSelect, palette }) {
  return <Pressable
    accessibilityRole="radio"
    accessibilityState={{ selected }}
    onPress={onSelect}
    style={[styles.resultRow, { borderBottomColor: palette.border, borderBottomWidth: bordered ? 1 : 0, backgroundColor: selected ? palette.accentSoft : 'transparent' }]}>
    <View style={[styles.resultDot, { borderColor: palette.border, backgroundColor: selected ? palette.accentStrong : 'transparent' }]} />
    <Text numberOfLines={1} style={[styles.resultTitle, { color: palette.text }]}>
      {result.title}{result.year ? ` (${result.year})` : ''}
    </Text>
  </Pressable>;
}

function RowCard({ row, labels, palette, onSearch, onResolve, onDismiss }) {
  const [open, setOpen] = useState(row.status === 'pending');
  const [query, setQuery] = useState(row.title);
  const [mediaType, setMediaType] = useState(row.mediaType);
  const [results, setResults] = useState(null);
  const [searchError, setSearchError] = useState(null);
  const [searching, setSearching] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [season, setSeason] = useState(String(row.seasonNumber ?? 1));
  const [episode, setEpisode] = useState(String(row.episodeNumber ?? 1));
  const [busy, setBusy] = useState(false);

  const pending = row.status === 'pending';
  const resolved = row.status === 'resolved';

  const runSearch = async () => {
    const title = query.trim();
    if (!title || searching) return;
    setSearching(true);
    setSearchError(null);
    setSelectedId(null);
    try {
      setResults(await onSearch({ query: title, mediaType }));
    } catch {
      setResults([]);
      setSearchError(labels.searchFailed);
    } finally {
      setSearching(false);
    }
  };

  const record = () => {
    if (!selectedId || busy) return;
    setBusy(true);
    const values = { media_type: mediaType, tmdb_id: selectedId };
    if (mediaType === 'tv') {
      values.season_number = season;
      values.episode_number = episode;
    }
    onResolve({ row, values });
  };

  const dismiss = () => {
    if (busy) return;
    setBusy(true);
    onDismiss({ row });
  };

  const statusText = resolved
    ? (row.resolvedTitle
      ? labels.resolved.replace('%(title)s', row.resolvedTitle)
      : labels.resolvedShort)
    : labels.dismissed;

  return <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: open }}
      onPress={() => setOpen(!open)}
      style={styles.summary}>
      <Text numberOfLines={1} style={[styles.title, { color: palette.text }]}>{row.title}</Text>
      <Text numberOfLines={1} style={[styles.meta, { color: palette.textMuted }]}>
        {formatDay(row.watchedAt)} · {row.mediaType}{!pending ? ` · ${resolved ? labels.resolvedShort : labels.dismissed}` : ''}
      </Text>
    </Pressable>
    {open ? <View style={[styles.body, { borderTopColor: palette.border }]}>
      {pending ? <>
        <View style={styles.searchRow}>
          <TextField labelHidden testID="netflix-review-query" value={query}
            onChangeText={setQuery} onSubmitEditing={runSearch}
            placeholder={labels.titleToSearch} accessibilityLabel={labels.titleToSearch} palette={palette} />
          <SelectField labelHidden testID="netflix-review-type"
            options={[{ value: 'movie', label: labels.movie }, { value: 'tv', label: labels.tv }]}
            value={mediaType} onChange={(change) => setMediaType(change.target.value)}
            accessibilityLabel={labels.mediaType} palette={palette} />
          <Button testID="netflix-review-search" label={searching ? labels.searching : labels.search}
            onPress={runSearch} disabled={searching || !query.trim()} palette={buttonPalette(palette)} />
        </View>
        {results === null ? <Text style={[styles.hint, { color: palette.textMuted }]}>{labels.searchHint}</Text>
          : results.length === 0
            ? <Text style={[styles.hint, { color: palette.textMuted }]}>{searchError || labels.noResults}</Text>
            : <View style={[styles.results, { borderColor: palette.border }]}>
              {results.map((result, index) => <ResultRow key={result.media_id} result={result}
                bordered={index < results.length - 1}
                selected={selectedId === result.media_id}
                onSelect={() => setSelectedId(result.media_id)} palette={palette} />)}
            </View>}
        {mediaType === 'tv' ? <View style={styles.coordinates}>
          <TextField testID="netflix-review-season" label={labels.season} labelHidden
            type="number" value={season} onChangeText={setSeason} palette={palette} />
          <TextField testID="netflix-review-episode" label={labels.episode} labelHidden
            type="number" value={episode} onChangeText={setEpisode} palette={palette} />
        </View> : null}
        <View style={styles.actions}>
          <Button testID="netflix-review-record" label={labels.record}
            onPress={record} disabled={!selectedId || busy} palette={buttonPalette(palette)} />
          <Button testID="netflix-review-dismiss" label={labels.dismiss} tone="ghost-danger"
            onPress={dismiss} disabled={busy} palette={buttonPalette(palette)} />
        </View>
      </> : <Text style={[styles.hint, { color: palette.textMuted }]}>
        {statusText}{row.resolvedAt ? ` · ${row.resolvedAt}` : ''}
      </Text>}
    </View> : null}
  </View>;
}

export function NetflixReviewView({ model, labels, palette, onSearch, onResolve, onDismiss }) {
  const copy = mergeLabels(labels);
  const rows = model.rows || [];
  return <View style={styles.list}>
    {rows.map((row) => <RowCard key={row.id} row={row} labels={copy}
      palette={palette} onSearch={onSearch} onResolve={onResolve} onDismiss={onDismiss} />)}
  </View>;
}

const styles = StyleSheet.create({
  list: { gap: 12 },
  card: { borderRadius: 10, borderWidth: 1, overflow: 'hidden' },
  summary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingVertical: 14 },
  title: { fontSize: 14, flex: 1 },
  meta: { fontSize: 13 },
  body: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 16, borderTopWidth: 1, gap: 12 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  results: { borderRadius: 8, borderWidth: 1 },
  resultRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: 1 },
  resultDot: { width: 14, height: 14, borderRadius: 7, borderWidth: 1.5 },
  resultTitle: { fontSize: 14, flex: 1 },
  coordinates: { flexDirection: 'row', gap: 8 },
  actions: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  hint: { fontSize: 13 },
});
