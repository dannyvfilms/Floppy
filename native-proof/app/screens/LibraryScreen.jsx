import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { AlphabetBar } from '../../../frontend/ui/AlphabetBar.native';
import { getActiveAuthSession } from '../data/authSession';
import { LibraryPageView } from '../../../frontend/pages/LibraryPageView';
import { createLibraryTransport, mediaRowsFromPayload } from '../data/libraryTransport';
import { createMusicTransport } from '../data/musicTransport';
import { mapBrowseList } from '../data/musicTransportCore';
import {
  cardModelsFromRows,
  defaultLibraryFilters,
  defaultSortDirection,
  filtersFromPreferences,
  filtersFromSavedQuery,
  libraryFilterOptions,
  libraryFilterSections,
  libraryMediaTypeTitle,
  libraryPastVerb,
  libraryQuery,
} from '../data/libraryTransportCore';
import { mediaCardPalette, palette, radius, spacing } from '../theme';
import BulkSlot from '../surfaces/BulkSlot';
import FiltersSlot, { LibrarySettingsMenu } from '../surfaces/FiltersSlot';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import TableSlot from '../surfaces/TableSlot';

const PAGE_LIMIT = 30;
const END_REACHED_PX = 480;

const labels = {
  loading: 'Loading your library…',
  retry: 'Try again',
};

// Web's music Media Type menu (filter_menu.html): Artists is the default.
const MUSIC_SUBVIEWS = [
  { value: 'artists', label: 'Artists' },
  { value: 'albums', label: 'Albums' },
  { value: 'tracks', label: 'Tracks' },
];
// Browse subviews: one tracked artist, album or podcast show per card, from
// the music and podcast endpoints (the web podcast page lists shows).
const BROWSE_SUBVIEWS = { artists: ['loadArtists', 'artist'], albums: ['loadAlbums', 'album'], shows: ['loadShows', 'show'] };

function browseCards(rows) {
  return rows.map(row => ({
    key: row.key,
    row,
    model: {
      mediaType: row.kind === 'show' ? 'podcast' : 'music',
      identity: { mediaType: row.kind === 'show' ? 'podcast' : 'music', mediaId: String(row.id), title: row.title },
      shape: 'poster',
      video: false,
      image: { src: row.image || null, fallback: '', source: 'primary' },
      title: row.title,
      altTitle: null,
      statusChip: null,
      cornerChips: [],
      titleLinks: [],
      progressBar: null,
      lines: [],
      rating: row.score != null && Number(row.score) > 0
        ? { label: String(row.score), value: Number(row.score), scaleMax: 10, rateLabel: 'Rate' }
        : null,
      ratingEditable: false,
      actions: null,
    },
  }));
}

// The A to Z rail the web shows from 768px up: All, #, A-Z.
const RAIL_MIN_WIDTH = 768;
const ALPHABET = [
  { value: '', label: 'All', caption: true, accessibilityLabel: 'All titles' },
  { value: '0-9', label: '#', accessibilityLabel: 'Titles starting with a number' },
  ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').map(letter => ({
    value: letter.toLowerCase(), label: letter, accessibilityLabel: `Titles starting with ${letter}`,
  })),
];
const RAIL_PALETTE = {
  interactiveStyle: {},
  focusStyle: {},
  badgeHover: palette.surfaceMuted,
  selectedText: palette.accent,
  mutedText: palette.textMuted,
  fontFamily: undefined,
  captionSize: 10,
  letterSize: 12,
};

function initialOf(title) {
  const first = String(title || '').trim().charAt(0).toLowerCase();
  if (!first) return 'other';
  if (/[0-9]/.test(first)) return '0-9';
  return /[a-z]/.test(first) ? first : 'other';
}

// Music and podcast subviews list artists, albums and shows from their own
// endpoints, so Status, Sort, the A to Z rail and Origin narrow those rows here.
const BROWSE_SORTS = [{ value: 'score', label: 'Rating' }, { value: 'title', label: 'Title' }];
function narrowBrowseRows(rows, filters) {
  const statuses = filters.statuses || [];
  const origin = String(filters.fields?.origin || '');
  const initial = filters.initial || '';
  let next = rows.filter(row => (!statuses.length || statuses.includes(row.status))
    && (!origin || String(row.country || '').toUpperCase() === origin.toUpperCase())
    && (!initial || initialOf(row.title) === initial));
  const direction = filters.direction === 'asc' ? 1 : -1;
  next = [...next].sort((left, right) => (filters.sort === 'title'
    ? String(left.title).localeCompare(String(right.title)) * direction
    : ((Number(left.score) || 0) - (Number(right.score) || 0)) * direction));
  return next;
}

// Sorts the table header can ask the server for (column key = sort value).
const TABLE_SORT_KEYS = ['title', 'score', 'progress', 'runtime', 'release_date', 'date_added'];

function LibrarySkeleton() {
  return <View accessibilityLabel="Loading" accessibilityLiveRegion="polite" style={styles.skeleton}>
    {Array.from({ length: 9 }, (_, index) => <View key={index} style={styles.skeletonCard} />)}
  </View>;
}

export default function LibraryScreen({ params, navigate, onOpenTab }) {
  const mediaType = params?.mediaType;
  const title = libraryMediaTypeTitle(mediaType);
  const [transport] = useState(() => createLibraryTransport());
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState(defaultLibraryFilters);
  const [filterData, setFilterData] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [filtersFor, setFiltersFor] = useState(mediaType);
  const [prefs, setPrefs] = useState({ loaded: false, columns: [], savedViews: [] });
  const savedPrefs = useRef({});
  const { width: windowWidth } = useWindowDimensions();
  if (filtersFor !== mediaType) {
    // Another library: its filters, options and selection are not this one's.
    setFiltersFor(mediaType);
    setFilters(defaultLibraryFilters());
    setFilterData(null);
    setSelectMode(false);
    setSelectedIds([]);
    setRows([]);
    setTotal(null);
    setPrefs({ loaded: false, columns: [], savedViews: [] });
    savedPrefs.current = {};
  }

  const query = useMemo(
    () => libraryQuery({ mediaType, limit: PAGE_LIMIT, filters }),
    [mediaType, filters],
  );
  const queryKey = JSON.stringify(query);
  // The filter menu lists what the status and list filters leave; sorting and
  // paging do not change it.
  const optionsKey = useMemo(() => {
    const { limit, offset, sort, direction, ...rest } = query;
    return JSON.stringify(rest);
  }, [query]);
  const isServer = transport.mode === 'server';
  const skipMain = !prefs.loaded || mediaType === 'podcast' || (mediaType === 'music' && (filters.fields?.subview || 'artists') !== 'tracks');

  // The viewer's saved layout, sort, status and columns come first, so the
  // page opens the way the web page does instead of with fixed defaults.
  useEffect(() => {
    if (!isServer || !mediaType) {
      setPrefs(current => ({ ...current, loaded: true }));
      return undefined;
    }
    let active = true;
    transport.loadPreferences(mediaType)
      .then(payload => {
        if (!active) return;
        const next = filtersFromPreferences(payload);
        savedPrefs.current = { layout: next.view, sort: next.sort, direction: next.direction, statuses: (payload.statuses || []).join(',') };
        setFilters(current => ({
          ...current, view: next.view, sort: next.sort, direction: next.direction, statuses: payload.statuses || [],
        }));
        setFilters(current => ({ ...current, separateEntries: Boolean(payload.separateEntries) }));
        setPrefs({ loaded: true, columns: payload.columns || [], savedViews: payload.savedViews || [], canSeparateEntries: Boolean(payload.canSeparateEntries), groupBy: payload.groupBy || [] });
      })
      .catch(() => { if (active) setPrefs(current => ({ ...current, loaded: true })); });
    return () => { active = false; };
  }, [transport, isServer, mediaType]);

  // Changing layout, sort, direction or status stores it for the next visit,
  // as the web media list does with its URL parameters.
  useEffect(() => {
    if (!isServer || !mediaType || !prefs.loaded) return;
    const current = { layout: filters.view, sort: filters.sort, direction: filters.direction, statuses: (filters.statuses || []).join(',') };
    const last = savedPrefs.current;
    if (!last.sort) { savedPrefs.current = current; return; }
    const patch = {};
    if (current.layout !== last.layout) patch.layout = current.layout;
    if (current.sort !== last.sort) patch.sort = current.sort;
    if (current.direction !== last.direction) patch.direction = current.direction;
    if (current.statuses !== last.statuses) patch.statuses = filters.statuses || [];
    if (!Object.keys(patch).length) return;
    savedPrefs.current = current;
    transport.savePreferences(mediaType, patch).catch(() => {});
  }, [transport, isServer, mediaType, prefs.loaded, filters.view, filters.sort, filters.direction, filters.statuses]);

  useEffect(() => {
    if (!isServer || skipMain) {
      setLoading(false);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError('');
    transport.load({ mediaType, filters, limit: PAGE_LIMIT })
      .then(payload => {
        if (!active) return;
        setRows(mediaRowsFromPayload(payload));
        const value = Number(payload?.pagination?.total);
        setTotal(Number.isFinite(value) ? value : null);
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
  }, [transport, mediaType, queryKey, isServer, skipMain, reloadToken]);

  // Option lists for the filter menu come from the server; a failed load
  // leaves the static choices (rating, collection, released) instead of
  // substituting sample values.
  useEffect(() => {
    if (!isServer || !mediaType) return undefined;
    let active = true;
    transport.loadFilterOptions({ mediaType, filters })
      .then(payload => { if (active) setFilterData(payload && !payload.local ? payload : null); })
      .catch(() => { if (active) setFilterData(null); });
    return () => { active = false; };
    // optionsKey stands for the filters that change the option lists.
  }, [transport, isServer, mediaType, optionsKey, reloadToken]);

  const subview = mediaType === 'music'
    ? (MUSIC_SUBVIEWS.some(entry => entry.value === filters.fields?.subview) ? filters.fields.subview : 'artists')
    : mediaType === 'podcast' ? 'shows' : null;
  const browse = BROWSE_SUBVIEWS[subview] || null;
  const [musicTransport] = useState(() => createMusicTransport());
  const [browseState, setBrowseState] = useState({ rows: [], loading: false, error: '' });

  const options = useMemo(() => {
    const base = libraryFilterOptions({ mediaType });
    base.sections = libraryFilterSections(mediaType, filterData);
    if (mediaType === 'game' && prefs.groupBy?.length) {
      base.sections.push({ key: 'group_by', label: 'Group By', state: 'group_by', type: 'single', clearValue: 'item', idleLabel: 'Item', options: prefs.groupBy, countAsFilter: false });
    }
    if (mediaType === 'music') {
      base.sections.unshift({
        key: 'subview', label: 'Media Type', state: 'subview', type: 'single', clearValue: 'artists', idleLabel: 'Artists', options: MUSIC_SUBVIEWS,
      });
      const subviewNow = subview;
      // Origin is an artist's country, listed from the artists themselves (web: show_origins).
      const origins = [...new Set(browseState.rows.filter(row => row.kind === 'artist' && row.country).map(row => row.country))].sort();
      if (subviewNow === 'artists' && origins.length) {
        base.sections.push({
          key: 'origin', label: 'Origin', state: 'origin', type: 'single', clearValue: '',
          options: origins.map(value => ({ value, label: value.length <= 3 ? value.toUpperCase() : value })),
        });
      }
    }
    if (browse) base.sorts = BROWSE_SORTS;
    return base;
  }, [mediaType, filterData, subview, browseState.rows, browse, prefs.groupBy]);

  useEffect(() => {
    if (!isServer || !browse) return undefined;
    let active = true;
    setBrowseState({ rows: [], loading: true, error: '' });
    musicTransport[browse[0]]()
      .then(payload => {
        if (!active) return;
        // The browse rows drop the album's artist id; the album opens under it.
        const rawById = new Map((payload?.results || []).filter(Boolean).map(raw => [Number(raw.id), raw]));
        const rows = mapBrowseList(payload, browse[1]).map(row => ({ ...row, artistId: Number(rawById.get(row.id)?.artist_id) || null, country: rawById.get(row.id)?.country || '' }));
        setBrowseState({ rows, loading: false, error: '' });
      })
      .catch(cause => { if (active) setBrowseState({ rows: [], loading: false, error: cause?.message || 'This list could not be loaded.' }); });
    return () => { active = false; };
  }, [musicTransport, isServer, browse, reloadToken]);

  function openBrowseRow(row) {
    navigate('Music', row.kind === 'artist' ? { artistId: row.id }
      : row.kind === 'album' ? { albumId: row.id, ...(row.artistId ? { artistId: row.artistId } : {}) } : { showId: row.id });
  }

  const groupedOverview = mediaType === 'game' && filters.fields?.group_by && filters.fields.group_by !== 'item' && !filters.fields.group;
  const view = browse || groupedOverview ? 'grid' : (filters.view || 'grid');

  function changeFilters(intent) {
    if (intent.type === 'clear') {
      setFilters(current => ({ ...defaultLibraryFilters(), view: current.view, separateEntries: current.separateEntries }));
      return;
    }
    setFilters(current => {
      if (intent.type === 'toggle') {
        const values = current[intent.key] || [];
        return {
          ...current,
          [intent.key]: values.includes(intent.value)
            ? values.filter(value => value !== intent.value)
            : [...values, intent.value],
        };
      }
      if (intent.type === 'set') {
        if (intent.key === 'sort' && intent.value !== current.sort) {
          return { ...current, sort: intent.value, direction: defaultSortDirection(intent.value) };
        }
        return { ...current, [intent.key]: intent.value };
      }
      if (intent.type === 'range') {
        return { ...current, ranges: { ...current.ranges, [intent.key]: intent.value } };
      }
      if (intent.type === 'toggleField') {
        const values = current.fields[intent.key] || [];
        return {
          ...current,
          fields: {
            ...current.fields,
            [intent.key]: values.includes(intent.value)
              ? values.filter(value => value !== intent.value)
              : [...values, intent.value],
          },
        };
      }
      if (intent.type === 'fieldMode') {
        return { ...current, modes: { ...current.modes, [intent.key]: intent.value } };
      }
      if (intent.type === 'field' || intent.type === 'clearField') {
        const section = options.sections.find(candidate => candidate.key === intent.key);
        const cleared = section?.type === 'multi' ? [] : (section?.clearValue ?? '');
        return {
          ...current,
          fields: { ...current.fields, ...(intent.key === 'group_by' ? { group: '', groupName: '' } : {}), [intent.key]: intent.type === 'clearField' ? cleared : intent.value },
        };
      }
      return current;
    });
  }

  // A header sort sets the server sort, like the toolbar's Sort menu: the same
  // column again flips the direction.
  function applySavedView(saved) {
    setFilters(current => filtersFromSavedQuery(saved.query, { ...defaultLibraryFilters(), separateEntries: current.separateEntries }));
  }

  async function saveView(name) {
    const created = await transport.createSavedView({ mediaType, name, filters });
    setPrefs(current => ({ ...current, savedViews: [...current.savedViews, created] }));
  }

  async function removeSavedView(saved) {
    await transport.deleteSavedView(saved.id);
    setPrefs(current => ({ ...current, savedViews: current.savedViews.filter(view => view.id !== saved.id) }));
  }

  async function shareView() {
    const url = await transport.shareView({ mediaType, filters });
    if (!url) throw new Error('The view could not be shared.');
    const server = String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '');
    await Linking.openURL(/^https?:/.test(url) ? url : `${server}${url}`);
  }

  function saveColumns(columns) {
    transport.savePreferences(mediaType, { columns }).then(next => {
      if (next?.columns) setPrefs(current => ({ ...current, columns: next.columns }));
    }).catch(() => {});
  }

  function sortBy(key) {
    setFilters(current => ({
      ...current,
      sort: key,
      direction: current.sort === key
        ? (current.direction === 'asc' ? 'desc' : 'asc')
        : defaultSortDirection(key),
    }));
  }

  function loadMore() {
    if (!isServer || loadingMore || loading || error) return;
    const nextOffset = rows.length;
    if (total != null && nextOffset >= total) return;
    setLoadingMore(true);
    transport.load({ mediaType, filters, limit: PAGE_LIMIT, offset: nextOffset })
      .then(payload => {
        const nextRows = mediaRowsFromPayload(payload);
        setRows(current => [
          ...current.filter(row => !nextRows.some(next => next.id === row.id && next.entryId === row.entryId)),
          ...nextRows,
        ]);
        setLoadingMore(false);
      })
      .catch(() => setLoadingMore(false));
  }

  function onScroll(event) {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    if (contentOffset.y + layoutMeasurement.height >= contentSize.height - END_REACHED_PX) loadMore();
  }

  function toggleItem(id) {
    setSelectedIds(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id]);
  }

  function toggleSelectMode() {
    if (selectMode) setSelectedIds([]);
    setSelectMode(!selectMode);
  }

  function openLibraryRow(row) {
    if (row.groupKey) {
      setFilters(current => ({ ...current, fields: { ...current.fields, group: row.groupKey, groupName: row.title } }));
      return;
    }
    navigate('Detail', { item: row });
  }

  const browseRows = useMemo(() => narrowBrowseRows(browseState.rows, filters), [browseState.rows, filters]);
  const shownRows = browse ? browseRows : rows;
  const shownLoading = browse ? browseState.loading : loading;
  const shownError = browse ? browseState.error : error;
  const state = shownLoading
    ? 'loading'
    : shownError
      ? 'error'
      : shownRows.length
        ? 'ready'
        : 'empty';

  // The first load shows placeholder cards in the grid's own shape, not a spinner.
  const skeleton = shownLoading && !shownRows.length;
  const hasMore = total != null && rows.length < total;
  const cards = useMemo(() => cardModelsFromRows(rows, { sort: filters.sort }), [rows, filters.sort]);

  const emptyState = !isServer
    ? { title: 'Sign in to see your library', body: 'Connect your Floppy server to load tracked media.' }
    : {
      title: `No ${title} Tracked Yet`,
      body: `Start tracking your ${title.toLowerCase()} to keep a record of what you've ${libraryPastVerb(mediaType)}.`,
      actionLabel: onOpenTab ? `Browse ${title}` : undefined,
    };

  const showRail = isServer && windowWidth >= RAIL_MIN_WIDTH && Boolean(mediaType);
  const railOptions = ALPHABET.map(option => ({ ...option, selected: option.value === (filters.initial || '') }));

  return <View style={styles.screen}>
    {showRail ? <View style={styles.rail}>
      <AlphabetBar options={railOptions} label="Filter by starting character" palette={RAIL_PALETTE}
        onNavigate={(_event, option) => setFilters(current => ({ ...current, initial: option.value }))} />
    </View> : null}
    <ScrollView
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      scrollEventThrottle={200}
      onScroll={onScroll}>
      <LibraryPageView
        title={title}
        titleStyle={{ fontSize: 30, lineHeight: 36 }}
        countStyle={{ paddingHorizontal: 8, paddingVertical: 8 }}
        count={browse ? (shownLoading ? undefined : shownRows.length) : total ?? (state === 'ready' ? rows.length : undefined)}
        headerActions={isServer && mediaType ? <LibrarySettingsMenu
          view={view}
          canToggleView={!browse && !groupedOverview}
          canSelect={!browse && !groupedOverview}
          selectMode={selectMode}
          onChangeView={next => changeFilters({ type: 'set', key: 'view', value: next })}
          onToggleSelect={toggleSelectMode}
          onShare={shareView}
          onSave={saveView}
          savedViews={prefs.savedViews}
          onApplySaved={applySavedView}
          onDeleteSaved={removeSavedView}
          separateEntries={Boolean(filters.separateEntries)}
          onToggleSeparate={prefs.canSeparateEntries ? async () => {
            const separateEntries = !filters.separateEntries;
            try {
              await transport.savePreferences(mediaType, { separateEntries });
              setFilters(current => ({ ...current, separateEntries }));
              setSelectMode(false);
              setSelectedIds([]);
            } catch (cause) { setError(cause?.message || 'The view could not be saved.'); }
          } : undefined} /> : null}
        labels={labels}
        palette={palette}
        state={skeleton ? 'ready' : state}
        error={shownError ? { title: 'Library could not load', body: shownError } : undefined}
        empty={emptyState}
        onRetry={() => setReloadToken(current => current + 1)}
        onEmptyAction={onOpenTab ? () => onOpenTab('discover') : undefined}
        filters={isServer ? <FiltersSlot
          filters={subview ? { ...filters, fields: { ...filters.fields, subview } } : filters}
          options={options}
          busy={loading}
          onChange={changeFilters} /> : null}
        groupBanner={mediaType === 'game' && filters.fields?.group ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' }}>
          <Pressable accessibilityRole="button" onPress={() => setFilters(current => ({ ...current, fields: { ...current.fields, group: '', groupName: '' } }))}
            style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, padding: spacing.sm, borderRadius: radius.sm, backgroundColor: palette.surface }}>
            <Icon spec={actionIcons.chevronLeft} size={16} color={palette.textSecondary} />
            <Text style={{ color: palette.textSecondary }}>All {prefs.groupBy?.find(option => option.value === filters.fields.group_by)?.label}</Text>
          </Pressable>
          <Text style={{ color: palette.text, fontSize: 18, fontWeight: '600' }}>{filters.fields.groupName}</Text>
        </View> : null}
        selection={<BulkSlot
          selectMode={selectMode}
          selectedIds={selectedIds}
          transport={transport}
          onLoadAllIds={() => transport.loadItemIds({ mediaType, filters })}
          onSelectIds={ids => setSelectedIds(ids.map(String))}
          onToggleSelectMode={toggleSelectMode}
          onClearSelection={() => setSelectedIds([])}
          onDone={() => setReloadToken(current => current + 1)} />}
        content={skeleton ? <LibrarySkeleton />
          : browse ? <MediaCardSlot
              items={browseCards(browseRows)}
              gridLayout="library"
              onOpenDetail={openBrowseRow}
              onOpenLink={() => {}} />
          : view === 'grid'
          ? <MediaCardSlot
              items={cards}
              gridLayout="library"
              selectionMode={selectMode}
              selectedKeys={cards.filter(card => selectedIds.includes(card.row.id)).map(card => card.key)}
              onToggleSelection={key => { const card = cards.find(card => card.key === key); if (card) toggleItem(card.row.id); }}
              onOpenDetail={openLibraryRow}
              onOpenLink={href => {
                if (String(href) === '/history') {
                  navigate('History');
                  return;
                }
                const row = rows.find(candidate => candidate.id === href);
                if (row) navigate('Detail', { item: row });
              }} />
          : <TableSlot
              rows={rows}
              mediaType={mediaType}
              sort={filters.sort}
              direction={filters.direction}
              sortableKeys={TABLE_SORT_KEYS.filter(key => options.sorts.some(sort => sort.value === key))}
              onSortChange={sortBy}
              selectMode={selectMode}
              selectedIds={selectedIds}
              onToggleItem={toggleItem}
              hasMore={hasMore}
              loadingMore={loadingMore}
              onLoadMore={loadMore}
              onOpenDetail={row => navigate('Detail', { item: row })}
              columnConfig={prefs.columns}
              onColumnsSave={saveColumns} />}
        footer={loadingMore && view === 'grid'
          ? <View style={styles.more}><ActivityIndicator color={palette.accentStrong} /></View>
          : null}
      />
    </ScrollView>
  </View>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, minHeight: 0 },
  rail: { position: 'absolute', right: spacing.xs, top: 160, bottom: spacing.lg, width: 32, zIndex: 20 },
  content: { paddingHorizontal: spacing.lg, paddingTop: spacing.xl, paddingBottom: spacing.xl, gap: spacing.lg },
  more: { alignItems: 'center', paddingVertical: spacing.lg },
  skeleton: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  skeletonCard: { width: '31.5%', aspectRatio: 2 / 3, borderRadius: 12, backgroundColor: palette.surfaceStrong },
});
