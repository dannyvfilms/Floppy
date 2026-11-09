import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { LibraryPageView } from '../../../frontend/pages/LibraryPageView';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { Button } from '../../../frontend/ui/Button';
import { Screen } from '../components/Screen';
import { createLibraryTransport, mediaRowsFromPayload } from '../data/libraryTransport';
import { libraryQuery } from '../data/libraryTransportCore';
import { palette, radius, spacing } from '../theme';
import LibraryGrid from '../surfaces/LibraryGrid';
import LibraryBulkActions from '../surfaces/LibraryBulkActions';
import TableSlot from '../surfaces/TableSlot';

const MEDIA_TYPE_LABELS = {
  movie: 'Movies',
  tv: 'Shows',
  anime: 'Anime',
  book: 'Books',
  comic: 'Comics',
  manga: 'Manga',
  game: 'Games',
  boardgame: 'Board Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

const PAGE_LIMIT = 30;
const STATUSES = [
  { value: 'planning', label: 'Planning' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'paused', label: 'Paused' },
  { value: 'completed', label: 'Completed' },
  { value: 'dropped', label: 'Dropped' },
  { value: 'no_status', label: 'No Status' },
];
const SORTS = [
  { value: 'date_added', label: 'Date added' },
  { value: 'title', label: 'Title' },
  { value: 'score', label: 'Rating' },
  { value: 'release_date', label: 'Release date' },
  { value: 'progress', label: 'Progress' },
  { value: 'end_date', label: 'Last watched' },
  { value: 'start_date', label: 'Start date' },
  { value: 'runtime', label: 'Runtime' },
  { value: 'time_watched', label: 'Time watched' },
  { value: 'plays', label: 'Plays' },
  { value: 'time_to_beat', label: 'Time to beat' },
  { value: 'platform', label: 'Platform' },
  { value: 'author', label: 'Author' },
  { value: 'popularity', label: 'Popularity' },
  { value: 'next_episode_air_date', label: 'Episode air date' },
  { value: 'time_left', label: 'Time left' },
];
const RANGE_UNITS = [
  { value: 'days', label: 'Days' }, { value: 'weeks', label: 'Weeks' },
  { value: 'months', label: 'Months' }, { value: 'years', label: 'Years' },
];
const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  radius: radius.sm,
  focusStyle: {},
};

const labels = {
  loading: 'Loading your library…',
  retry: 'Try again',
  emptyTitle: 'Nothing here yet',
  emptyAction: 'Browse Discover',
};

export default function LibraryScreen({ params, navigate }) {
  const mediaType = params?.mediaType;
  const title = MEDIA_TYPE_LABELS[mediaType] || 'Library';
  const [transport] = useState(() => createLibraryTransport());
  const [filters, setFilters] = useState(() => ({
    mediaTypes: mediaType && mediaType !== 'all' ? [mediaType] : [],
    statuses: [], sort: 'date_added', direction: 'desc', view: 'grid',
    ranges: {
      rating: { from: '', to: '', within: '', unit: 'days' },
      dateAdded: { from: '', to: '', within: '', unit: 'days' },
      releaseDate: { from: '', to: '', within: '', unit: 'days' },
      completedDate: { from: '', to: '', within: '', unit: 'days' },
    },
    fields: { genre: '', year: '', tags: [] },
    modes: { tags: 'or' },
  }));
  const [search, setSearch] = useState('');
  const [querySearch, setQuerySearch] = useState('');
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedRows, setSelectedRows] = useState([]);
  const [savedViews, setSavedViews] = useState([]);
  const [savedViewName, setSavedViewName] = useState('');
  const [tagOptions, setTagOptions] = useState([]);
  const [subview, setSubview] = useState(params?.subview || (mediaType === 'comic' ? 'comics' : 'items'));
  const [groupBy, setGroupBy] = useState(params?.groupBy || 'item');
  const queryState = useMemo(() => ({
    mediaType: filters.mediaTypes?.length === 1 ? filters.mediaTypes[0]
      : filters.mediaTypes?.length ? 'all' : mediaType,
    media_type: filters.mediaTypes?.length > 1 ? filters.mediaTypes : undefined,
    search: querySearch,
    statuses: filters.statuses,
    sort: filters.sort,
    direction: filters.direction,
    ranges: filters.ranges,
    fields: filters.fields,
    modes: filters.modes,
    rating: filters.rating,
    collection: filters.collection,
    progress: filters.progress,
    group_by: groupBy,
    subview,
  }), [filters, groupBy, mediaType, querySearch, subview]);
  const queryKey = JSON.stringify(queryState);
  const activeQueryKey = useRef(queryKey);

  useEffect(() => {
    const timer = setTimeout(() => setQuerySearch(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (transport.mode !== 'server') {
      setLoading(false);
      return undefined;
    }
    let active = true;
    activeQueryKey.current = queryKey;
    setSelectionMode(false);
    setSelectedRows([]);
    setLoading(true);
    setLoadingMore(false);
    setError('');
    setRows([]);
    transport.load({ ...queryState, limit: PAGE_LIMIT, offset: 0 })
      .then(payload => {
        if (!active) return;
        const nextRows = mediaRowsFromPayload(payload, { subview });
        setRows(nextRows);
        const value = Number(payload?.pagination?.total);
        setTotal(Number.isFinite(value) ? value : null);
        setHasMore(Boolean(payload?.pagination?.next));
        setLoading(false);
      })
      .catch(cause => {
        if (!active) return;
        setRows([]);
        setTotal(null);
        setError(cause?.message || 'Your library could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, queryState, queryKey, reloadToken]);

  useEffect(() => {
    if (transport.mode !== 'server' || !mediaType || mediaType === 'all') {
      setSavedViews([]);
      return undefined;
    }
    let active = true;
    transport.loadSavedViews({ mediaType }).then(views => {
      if (active) setSavedViews(Array.isArray(views) ? views : []);
    }).catch(() => {
      if (active) setSavedViews([]);
    });
    return () => { active = false; };
  }, [transport, mediaType]);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    transport.loadTags().then(payload => {
      if (active) setTagOptions((payload?.results || []).map(tag => ({ value: String(tag.id), label: tag.name })));
    }).catch(() => { if (active) setTagOptions([]); });
    return () => { active = false; };
  }, [transport]);

  function changeFilter(intent) {
    if (intent.type === 'clear') {
      setFilters(current => ({ ...current, statuses: [], sort: 'date_added', direction: 'desc',
        ranges: Object.fromEntries(Object.entries(current.ranges).map(([key, range]) => [key, { ...range, from: '', to: '', within: '' }])),
        fields: { genre: '', year: '', selectedTags: [] }, modes: { tags: 'or' } }));
      setSearch('');
    } else if (intent.type === 'toggle') {
      setFilters(current => ({ ...current, [intent.key]: current[intent.key].includes(intent.value)
        ? current[intent.key].filter(value => value !== intent.value)
        : [...current[intent.key], intent.value] }));
    } else if (intent.type === 'set') {
      setFilters(current => ({ ...current, [intent.key]: intent.value }));
    } else if (intent.type === 'range') {
      setFilters(current => ({ ...current, ranges: { ...current.ranges, [intent.key]: intent.value } }));
    } else if (intent.type === 'field') {
      setFilters(current => ({ ...current, fields: { ...current.fields, [intent.key]: intent.value } }));
    } else if (intent.type === 'toggleField') {
      setFilters(current => {
        const values = current.fields[intent.key] || [];
        return { ...current, fields: { ...current.fields,
          [intent.key]: values.includes(intent.value) ? values.filter(value => value !== intent.value) : [...values, intent.value] } };
      });
    } else if (intent.type === 'fieldMode') {
      setFilters(current => ({ ...current, modes: { ...current.modes, [intent.key]: intent.value } }));
    } else if (intent.type === 'savedView') {
      transport.applySavedView?.({ id: intent.value }).then(saved => {
        const params = new URLSearchParams(saved?.query || '');
        setSearch(params.get('search') || '');
        setFilters(current => ({
          ...current,
          statuses: params.getAll('status'),
          sort: params.get('sort') || 'date_added',
          direction: params.get('direction') || 'desc',
          view: params.get('layout') || current.view,
          rating: params.get('rating') || 'all',
          collection: params.get('collection') || 'all',
          progress: params.get('progress') || 'all',
          fields: { ...current.fields, genre: params.get('genre') || '', year: params.get('year') || '',
            tags: params.getAll('tags') },
          modes: { ...current.modes, tags: params.get('tag_mode') || 'or' },
          ranges: {
            ...current.ranges,
            rating: { ...current.ranges.rating, from: params.get('rating_min') || '', to: params.get('rating_max') || '' },
            dateAdded: { ...current.ranges.dateAdded, from: params.get('date_added_from') || '',
              to: params.get('date_added_to') || '', within: params.get('date_added_within') || '',
              unit: params.get('date_added_within_unit') || 'days' },
            releaseDate: { ...current.ranges.releaseDate, from: params.get('release_date_from') || '',
              to: params.get('release_date_to') || '', within: params.get('release_date_within') || '',
              unit: params.get('release_date_within_unit') || 'days' },
            completedDate: { ...current.ranges.completedDate, from: params.get('completed_date_from') || '',
              to: params.get('completed_date_to') || '', within: params.get('completed_date_within') || '',
              unit: params.get('completed_date_within_unit') || 'days' },
          },
        }));
      }).catch(cause => setError(cause?.message || 'Saved view could not be loaded.'));
    }
  }

  function savedViewQuery() {
    const params = new URLSearchParams();
    const query = libraryQuery({ ...queryState, layout: filters.view });
    Object.entries(query).forEach(([key, value]) => {
      if (value == null || ['limit', 'offset', 'media_type'].includes(key)) return;
      const values = Array.isArray(value) ? value : [value];
      values.forEach(item => params.append(key, String(item)));
    });
    return params.toString();
  }

  async function saveCurrentView() {
    const name = savedViewName.trim();
    if (!name || transport.mode !== 'server' || !mediaType || mediaType === 'all') return;
    try {
      const saved = await transport.createSavedView({ mediaType, name, query: savedViewQuery() });
      setSavedViews(current => [...current, saved]);
      setSavedViewName('');
    } catch (cause) {
      setError(cause?.message || 'Saved view could not be created.');
    }
  }

  async function deleteSavedView(id) {
    try {
      await transport.deleteSavedView({ id });
      setSavedViews(current => current.filter(view => view.id !== id));
    } catch (cause) {
      setError(cause?.message || 'Saved view could not be deleted.');
    }
  }

  async function moveSavedView(id, direction) {
    const index = savedViews.findIndex(view => view.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= savedViews.length) return;
    const reordered = [...savedViews];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    try {
      await transport.reorderSavedViews({ mediaType, ids: reordered.map(view => view.id) });
      setSavedViews(reordered);
    } catch (cause) {
      setError(cause?.message || 'Saved views could not be reordered.');
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    const requestedQuery = queryKey;
    setLoadingMore(true);
    setError('');
    try {
      const payload = await transport.load({ ...queryState, limit: PAGE_LIMIT, offset: rows.length });
      if (activeQueryKey.current === requestedQuery) {
        setRows(current => [...current, ...mediaRowsFromPayload(payload, { subview })]);
        setHasMore(Boolean(payload?.pagination?.next));
      }
    } catch (cause) {
      if (activeQueryKey.current === requestedQuery) {
        setError(cause?.message || 'More library items could not be loaded.');
      }
    } finally {
      setLoadingMore(false);
    }
  }

  function toggleSelected(id) {
    setSelectedRows(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  }

  const dynamicGenres = [...new Set(rows.flatMap(row => row.media?.item?.genres || []))].map(value => ({ value, label: value }));
  const dynamicYears = [...new Set(rows.map(row => {
    const value = row.media?.item?.release_datetime;
    return value ? String(new Date(value).getUTCFullYear()) : '';
  }).filter(Boolean))].map(value => ({ value, label: value })).sort((a, b) => b.value.localeCompare(a.value));
  const musicSubview = mediaType === 'music' && ['artists', 'albums'].includes(subview);
  const filterOptions = {
    mediaTypes: Object.entries(MEDIA_TYPE_LABELS).map(([value, label]) => ({ value, label })),
    statuses: musicSubview ? [
      { value: '0', label: 'Planning' }, { value: '1', label: 'In progress' },
      { value: '2', label: 'Paused' }, { value: '3', label: 'Completed' }, { value: '4', label: 'Dropped' },
      { value: 'no_status', label: 'No Status' },
    ] : STATUSES,
    sorts: (musicSubview ? SORTS.filter(option => ['date_added', 'title', 'score', 'release_date', 'start_date', 'end_date'].includes(option.value)) : SORTS)
      .filter(option => !(option.value === 'time_left' && mediaType !== 'tv')
      && !(option.value === 'time_to_beat' && mediaType !== 'game')
      && !(option.value === 'platform' && mediaType !== 'game')),
    views: [{ value: 'grid', label: 'Grid' }, { value: 'table', label: 'Table' }],
    savedViews: savedViews.map(view => ({ id: String(view.id), label: view.name })),
    ranges: musicSubview ? [
      { key: 'rating', label: 'Rating', type: 'number', placeholder: '0–10' },
    ] : [
      { key: 'rating', label: 'Rating', type: 'number', placeholder: '0–10' },
      ...['dateAdded', 'releaseDate', 'completedDate'].map((key, index) => ({
        key, label: ['Date added', 'Release date', 'Completed date'][index], type: 'date',
        placeholder: 'YYYY-MM-DD', relative: true, units: RANGE_UNITS,
      })),
    ],
    sections: musicSubview ? [] : [
      { key: 'genre', label: 'Genre', state: 'genre', type: 'single', clearValue: '', searchable: true, options: dynamicGenres },
      { key: 'year', label: 'Year', state: 'year', type: 'single', clearValue: '', searchable: true, options: dynamicYears },
      { key: 'tags', label: 'Tags', type: 'multi', clearValue: [], searchable: true, modeValue: 'or',
        modes: [{ value: 'or', label: 'Any' }, { value: 'and', label: 'All' }, { value: 'not', label: 'Not' }],
        modeState: 'tags', options: tagOptions },
    ],
  };

  const state = loading
    ? 'loading'
    : error && rows.length === 0
      ? 'error'
      : rows.length
        ? 'ready'
        : 'empty';

  return <Screen chrome={false}>
    <LibraryPageView
      title={title}
      subtitle="Everything you track, filtered the way you left it"
      count={total ?? (state === 'ready' ? rows.length : undefined)}
      countLabel={total === 1 ? 'item' : 'items'}
      labels={labels}
      palette={palette}
      state={state}
      error={error ? { title: 'Library could not load', body: error } : undefined}
      empty={transport.mode === 'local'
        ? { title: 'Sign in to see your library', body: 'Connect your Floppy server to load tracked media.' }
        : { title: 'Nothing here yet', body: 'Track something and it will appear in this library.' }}
      onRetry={() => setReloadToken(current => current + 1)}
      onEmptyAction={() => navigate('Discover')}
      search={<View style={styles.searchGroup}>
        <TextInput value={search} onChangeText={setSearch} placeholder="Search your library…"
          placeholderTextColor={palette.textMuted} accessibilityLabel="Search your library"
          returnKeyType="search" style={styles.searchInput} />
        {mediaType && mediaType !== 'all' ? <View style={styles.saveViewRow}>
          <TextInput value={savedViewName} onChangeText={setSavedViewName} placeholder="Name this view"
            placeholderTextColor={palette.textMuted} accessibilityLabel="Saved view name" style={styles.nameInput} />
          <Button label="Save view" tone="surface" disabled={!savedViewName.trim()}
            onPress={saveCurrentView} palette={buttonPalette} />
        </View> : null}
        {savedViews.map(view => <View key={view.id} style={styles.savedViewRow}>
          <Text style={styles.savedViewName}>{view.name}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={`Move ${view.name} up`}
            disabled={savedViews[0]?.id === view.id} onPress={() => moveSavedView(view.id, -1)}>
            <Text style={styles.reorderView}>↑</Text></Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={`Move ${view.name} down`}
            disabled={savedViews[savedViews.length - 1]?.id === view.id} onPress={() => moveSavedView(view.id, 1)}>
            <Text style={styles.reorderView}>↓</Text></Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${view.name} saved view`}
            onPress={() => deleteSavedView(view.id)}><Text style={styles.deleteSavedView}>Delete</Text></Pressable>
        </View>)}
      </View>}
      filters={<View style={styles.controls}>
        <FilterBar filters={filters} options={filterOptions} palette={palette} resultCount={total}
          busy={loading || loadingMore} onChange={changeFilter} />
        {mediaType === 'game' ? <View style={styles.modeRow}>
          {['item', 'series', 'franchise'].map(value => <Pressable key={value}
            accessibilityRole="button" accessibilityState={{ selected: groupBy === value }}
            onPress={() => setGroupBy(value)} style={[styles.modeButton, groupBy === value && styles.modeButtonActive]}>
            <Text style={styles.modeText}>{value[0].toUpperCase() + value.slice(1)}</Text>
          </Pressable>)}
        </View> : null}
        {mediaType === 'comic' ? <View style={styles.modeRow}>
          {['comics', 'issues'].map(value => <Pressable key={value}
            accessibilityRole="button" accessibilityState={{ selected: subview === value }}
            onPress={() => setSubview(value)} style={[styles.modeButton, subview === value && styles.modeButtonActive]}>
            <Text style={styles.modeText}>{value === 'issues' ? 'Issues' : 'Comics'}</Text>
          </Pressable>)}
        </View> : null}
        {mediaType === 'music' ? <View style={styles.modeRow}>
          {['items', 'artists', 'albums'].map(value => <Pressable key={value}
            accessibilityRole="button" accessibilityState={{ selected: subview === value }}
            onPress={() => setSubview(value)} style={[styles.modeButton, subview === value && styles.modeButtonActive]}>
            <Text style={styles.modeText}>{value[0].toUpperCase() + value.slice(1)}</Text>
          </Pressable>)}
        </View> : null}
        {!(mediaType === 'music' && ['artists', 'albums'].includes(subview)) ? <LibraryBulkActions rows={rows} selectedRows={selectedRows}
          transport={transport} selecting={selectionMode}
          onToggleSelect={() => { setSelectionMode(value => !value); setSelectedRows([]); }}
          onClearSelection={() => setSelectedRows([])}
          onDone={() => { setReloadToken(value => value + 1); setSelectedRows([]); setSelectionMode(false); }} /> : null}
      </View>}
      content={filters.view === 'grid'
        ? <LibraryGrid rows={rows} selecting={selectionMode} selected={selectedRows} onToggle={toggleSelected} groupBy={groupBy}
          onOpen={row => navigate('Detail', { item: row })}
          onRate={(row, score) => transport.update({ identity: row.identity, values: { score } })
            .then(() => setReloadToken(value => value + 1))
            .catch(cause => setError(cause?.message || 'Rating could not be saved.'))} />
        : <TableSlot rows={rows} onOpenDetail={row => navigate('Detail', { item: row })}
          selecting={selectionMode} selectedRows={selectedRows} onToggleSelect={toggleSelected}
          querySort={filters.sort} queryDirection={filters.direction}
          onQuerySort={(sort, direction) => setFilters(current => ({ ...current, sort, direction }))}
          onTrackSave={(row, values) => transport.update({ identity: row.identity, values })
            .then(() => setReloadToken(value => value + 1))}
          onTrackDelete={row => transport.remove({ identity: row.identity })
            .then(() => setReloadToken(value => value + 1))} />}
      footer={<View style={styles.footer}>
        {error ? <Text accessibilityRole="alert" style={styles.inlineError}>{error}</Text> : null}
        {hasMore ? <Button label="Load more" tone="surface" busy={loadingMore}
          disabled={loadingMore} onPress={loadMore} palette={buttonPalette} /> : null}
        {loadingMore ? <ActivityIndicator color={palette.accent} /> : null}
      </View>}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  searchGroup: { width: '100%' },
  searchInput: { color: palette.text, backgroundColor: palette.surface, borderColor: palette.border,
    borderWidth: 1, borderRadius: radius.sm, minHeight: 44, paddingHorizontal: spacing.md, fontSize: 15 },
  saveViewRow: { flexDirection: 'row', gap: spacing.sm },
  nameInput: { flex: 1, minWidth: 120, color: palette.text, backgroundColor: palette.surface,
    borderColor: palette.border, borderWidth: 1, borderRadius: radius.sm, minHeight: 40,
    paddingHorizontal: spacing.md, fontSize: 14 },
  savedViewRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: spacing.xs, borderBottomWidth: 1, borderColor: palette.border },
  savedViewName: { color: palette.textSecondary, fontSize: 13 },
  reorderView: { color: palette.textSecondary, fontSize: 18, paddingHorizontal: spacing.xs },
  deleteSavedView: { color: palette.danger, fontSize: 13, padding: spacing.xs },
  controls: { gap: spacing.sm },
  modeRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  modeButton: { borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface,
    borderRadius: radius.sm, paddingVertical: 8, paddingHorizontal: spacing.md },
  modeButtonActive: { borderColor: palette.accent, backgroundColor: palette.surfaceStrong },
  modeText: { color: palette.text, fontSize: 13, textTransform: 'capitalize' },
  selectedCount: { color: palette.textSecondary, fontSize: 13 },
  footer: { gap: spacing.sm, alignItems: 'center' },
  inlineError: { color: palette.danger, fontSize: 13 },
});
