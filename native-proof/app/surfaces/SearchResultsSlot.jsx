import React, { useEffect, useRef, useState } from 'react';
import { Text } from 'react-native';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { SearchResults } from '../../../frontend/ui/SearchResults';
import { palette, mediaCardPalette, radius } from '../theme';
import {
  createSearchTransport,
  localResultsFromPayload,
  onlineResultsFromPayload,
} from '../data/searchTransport';

export const surface = {
  id: 'SEARCH-RESULTS',
  status: 'in_progress',
  title: 'Search result sections, paging and source scope',
  where: 'Search results',
  note: 'The shared SearchResults view keeps grouped local sections, online sections, source scope, grid/list layouts, paging, load-more, empty/loading/error states and rating stars. Signed-in search queries /api/v1/media/ (all media types group the local library) and /api/v1/search/{media_type}/ for provider results through the session facade; the demo fixtures are gone. Rating changes stay local because the search endpoint returns untracked candidates and the demo never persisted them.',
};

const labels = {
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
};

const searchPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  accent: palette.accent,
  accentText: '#ffffff',
  link: '#818cf8',
  danger: palette.danger,
  radius: radius.sm,
  ...mediaCardPalette,
};

const TYPE_LABEL = {
  movie: 'Movies',
  tv: 'TV',
  anime: 'Anime',
  book: 'Books',
  manga: 'Manga',
  comic: 'Comics',
  game: 'Games',
  boardgame: 'Board Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

const SOURCE_OPTIONS = {
  movie: [
    { value: 'tmdb', label: 'TMDB' },
    { value: 'tvdb', label: 'TheTVDB', unavailable: true },
  ],
  tv: [
    { value: 'tmdb', label: 'TMDB' },
    { value: 'tvdb', label: 'TheTVDB', unavailable: true },
  ],
  book: [
    { value: 'openlibrary', label: 'Open Library' },
    { value: 'hardcover', label: 'Hardcover' },
  ],
  music: [{ value: 'musicbrainz', label: 'MusicBrainz' }],
};

const DEFAULT_SOURCE = {
  movie: 'tmdb',
  tv: 'tmdb',
  book: 'openlibrary',
  music: 'musicbrainz',
};

const ONLINE_PAGE_SIZE = 20;
const LOCAL_ALL_LIMIT = 60;
const LOCAL_LIMIT = 24;

function resultModel(item, ratings) {
  const rated = ratings[item.key];
  const value = rated ?? item.rating;
  return {
    mediaType: item.type,
    shape: 'poster',
    href: item.href || '',
    identity: item.identity || null,
    image: { src: item.image, fallback: '', source: 'primary' },
    title: item.title,
    altTitle: null,
    statusChip: item.status ? { kind: 'status', status: item.status, label: item.status } : null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: [{ join: 'plain', parts: [{ text: item.year || '' }, { text: item.note ? `• ${item.note}` : '', muted: true }] }],
    rating: value == null ? null : {
      label: String(value),
      value,
      scaleMax: 10,
      rateLabel: 'Rate',
    },
    ratingEditable: true,
    actions: null,
  };
}

export default function SearchResultsSlot({ query = '', mediaType: initialMediaType = 'all', onOpenDetail }) {
  const [transport] = useState(() => createSearchTransport());
  const [mediaType, setMediaType] = useState(initialMediaType || 'all');
  const [layout, setLayout] = useState('grid');
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [source, setSource] = useState(DEFAULT_SOURCE[initialMediaType] || null);
  const [page, setPage] = useState(1);
  const [visibleLocal, setVisibleLocal] = useState(6);
  const [loadingMore, setLoadingMore] = useState(false);
  const [status, setStatus] = useState(transport.mode === 'server' ? 'loading' : 'empty');
  const [request, setRequest] = useState(0);
  const [ratings, setRatings] = useState({});
  const [localItems, setLocalItems] = useState([]);
  const [localTotal, setLocalTotal] = useState(0);
  const [onlineItems, setOnlineItems] = useState([]);
  const [onlineTotal, setOnlineTotal] = useState(0);
  const loadTimer = useRef(null);
  const queryTimer = useRef(null);

  useEffect(() => {
    setMediaType(initialMediaType || 'all');
  }, [initialMediaType]);

  useEffect(() => {
    setSource(DEFAULT_SOURCE[mediaType] || null);
    setPage(1);
    setVisibleLocal(6);
    setOnlineOnly(false);
  }, [mediaType, query]);

  useEffect(() => () => {
    clearTimeout(loadTimer.current);
    clearTimeout(queryTimer.current);
  }, []);

  const sourceOptions = SOURCE_OPTIONS[mediaType] || [];
  const activeSource = sourceOptions.find(option => option.value === source) || sourceOptions[0] || null;

  useEffect(() => {
    if (transport.mode !== 'server') {
      setStatus('empty');
      setLocalItems([]);
      setOnlineItems([]);
      return undefined;
    }
    const needle = String(query || '').trim();
    if (!needle) {
      setStatus('empty');
      setLocalItems([]);
      setOnlineItems([]);
      setLocalTotal(0);
      setOnlineTotal(0);
      return undefined;
    }
    let active = true;
    setStatus('loading');
    setLoadingMore(false);
    clearTimeout(queryTimer.current);
    const isAll = mediaType === 'all';
    const localRequest = transport.searchLocal({
      search: needle,
      mediaType: isAll ? 'all' : mediaType,
      limit: isAll ? LOCAL_ALL_LIMIT : LOCAL_LIMIT,
      offset: 0,
    });
    const onlineRequest = isAll || activeSource?.unavailable
      ? Promise.resolve(null)
      : transport.searchOnline({
        search: needle,
        mediaType,
        source: activeSource?.value,
        limit: ONLINE_PAGE_SIZE,
        offset: (page - 1) * ONLINE_PAGE_SIZE,
      });
    queryTimer.current = setTimeout(() => {
      Promise.allSettled([localRequest, onlineRequest]).then(([localResult, onlineResult]) => {
        if (!active) return;
        let failed = false;
        if (localResult.status === 'fulfilled') {
          setLocalItems(localResultsFromPayload(localResult.value));
          const total = Number(localResult.value?.pagination?.total);
          setLocalTotal(Number.isFinite(total) ? total : 0);
        } else {
          failed = true;
        }
        if (onlineResult.status === 'fulfilled' && onlineResult.value) {
          setOnlineItems(onlineResultsFromPayload(onlineResult.value));
          const total = Number(onlineResult.value?.pagination?.total);
          setOnlineTotal(Number.isFinite(total) ? total : 0);
        } else {
          setOnlineItems([]);
          setOnlineTotal(0);
        }
        setStatus(failed ? 'error' : 'ready');
      });
    }, 300);
    return () => {
      active = false;
      clearTimeout(queryTimer.current);
    };
  }, [transport, query, mediaType, source, page, request, activeSource?.value, activeSource?.unavailable]);

  const model = (item) => resultModel(item, ratings);

  const localMatches = localItems;
  const onlineMatches = onlineItems;
  const pageCount = Math.max(1, Math.ceil((onlineTotal || onlineMatches.length) / ONLINE_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);

  const sections = [];
  if (status === 'ready' || (status === 'loading' && localItems.length)) {
    if (mediaType === 'all') {
      Object.keys(TYPE_LABEL).forEach(type => {
        const items = localItems.filter(item => item.type === type);
        if (!items.length) return;
        sections.push({
          key: type,
          title: TYPE_LABEL[type],
          totalLabel: `${items.length} results`,
          subsections: [{ key: type, items: items.map(model), layout }],
        });
      });
    } else {
      const visible = localMatches.slice(0, visibleLocal);
      if (!onlineOnly && visible.length) {
        sections.push({
          key: 'local',
          title: 'In Your Library',
          totalLabel: `${localMatches.length} results`,
          shownLabel: localMatches.length > visible.length ? `· Showing first ${visible.length}` : null,
          searchOnline: { label: 'Search online' },
          subsections: [{ key: 'local', items: visible.map(model), layout }],
        });
      }
      if (onlineMatches.length) {
        sections.push({
          key: 'online',
          title: 'Online Results',
          totalLabel: `${onlineTotal || onlineMatches.length} results`,
          subsections: [{ key: 'online', items: onlineMatches.map(model), layout }],
        });
      }
    }
  }

  const paging = onlineMatches.length && !onlineOnly ? {
    page: currentPage,
    totalPages: pageCount,
    totalResults: onlineTotal || onlineMatches.length,
    previous: currentPage > 1 ? { number: currentPage - 1 } : null,
    next: currentPage < pageCount ? { number: currentPage + 1 } : null,
    pages: Array.from({ length: pageCount }, (_, index) => ({
      number: index + 1,
      current: index + 1 === currentPage,
    })),
    summary: `Page ${currentPage} of ${pageCount} (${onlineTotal || onlineMatches.length} results)`,
  } : null;

  const hasMore = mediaType !== 'all' && !onlineOnly && visibleLocal < localMatches.length;
  const viewState = status === 'loading' && !sections.length
    ? 'loading'
    : status === 'error' && !sections.length
      ? 'error'
      : sections.length
        ? 'ready'
        : 'empty';
  const sourceScope = sourceOptions.length ? {
    label: 'Source:',
    options: sourceOptions.map(option => ({
      value: option.value,
      label: option.label,
      active: option.value === activeSource?.value,
    })),
  } : { label: '', options: [] };

  function selectSource(option) {
    setSource(option.value);
    setPage(1);
  }

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    loadTimer.current = setTimeout(() => {
      setVisibleLocal(current => current + 6);
      setLoadingMore(false);
    }, 200);
  }

  function retry() {
    if (activeSource?.unavailable) {
      setSource(DEFAULT_SOURCE[mediaType] || null);
      return;
    }
    setRequest(current => current + 1);
  }

  return <SearchResults
    title={query ? `Search results for “${query}”` : 'Search Results'}
    state={viewState}
    labels={labels}
    palette={searchPalette}
    scope={sourceScope}
    layoutOptions={[
      { value: 'grid', label: 'Grid View', glyph: '▦', active: layout === 'grid' },
      { value: 'list', label: 'List View', glyph: '☰', active: layout === 'list' },
    ]}
    notes={[
      ...(onlineOnly ? [`Showing online results for “${query}”.`] : []),
      ...(mediaType === 'all' ? ['Searching your library only: pick a media type to search online.'] : []),
      ...(activeSource?.unavailable ? [`${activeSource.label} is not connected in this preview.`] : []),
    ]}
    sections={sections}
    paging={paging}
    hasMore={hasMore}
    loadingMore={loadingMore}
    empty={{
      title: status === 'error' ? 'Search could not load' : 'No results found',
      body: status === 'error'
        ? 'Please try again.'
        : `We couldn't find any matches for “${query}”. Try checking the spelling or using a different media type.`,
    }}
    onSelectScope={selectSource}
    onSelectLayout={option => setLayout(option.value)}
    onSearchOnline={() => {
      setOnlineOnly(true);
      setPage(1);
    }}
    onOpenResult={href => onOpenDetail?.(href)}
    onPage={nextPage => setPage(nextPage?.number || 1)}
    onLoadMore={loadMore}
    onRetry={retry}
    onRate={(item, score) => {
      const key = item?.identity
        ? `${item.identity.mediaType}-${item.identity.source}-${item.identity.mediaId}`
        : item?.href?.split('/').pop();
      if (key) setRatings(current => ({ ...current, [key]: score }));
    }}
    renderRating={({ value, label, scaleMax, palette: ratingPalette, onSelect }) => <RatingStars
      scaleMax={scaleMax}
      value={value}
      label={label}
      onSelect={onSelect}
      palette={ratingPalette}
      renderStar={() => <Text style={{ color: ratingPalette.lit, fontSize: 22 }}>★</Text>}
    />}
  />;
}