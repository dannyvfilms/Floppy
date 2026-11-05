import React, { useEffect, useRef, useState } from 'react';
import { Text } from 'react-native';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { SearchResults } from '../../../frontend/ui/SearchResults';
import { palette, mediaCardPalette, radius } from '../theme';

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
  book: 'Books',
  music: 'Music',
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

const LIBRARY_ITEMS = [
  { key: 'dune', type: 'movie', title: 'Dune', year: '2021', note: '2h 35m', image: 'https://picsum.photos/seed/floppy-dune/400/600', status: 'Completed', rating: 9 },
  { key: 'dune-two', type: 'movie', title: 'Dune: Part Two', year: '2024', note: '2h 46m', image: 'https://picsum.photos/seed/floppy-dune-two/400/600', status: 'Completed', rating: 9 },
  { key: 'dune-1984', type: 'movie', title: 'Dune', year: '1984', note: '2h 17m', image: 'https://picsum.photos/seed/floppy-dune-1984/400/600', status: 'Paused', rating: 6 },
  { key: 'dune-messiah', type: 'book', title: 'Dune Messiah', year: '1969', note: 'Frank Herbert', image: 'https://picsum.photos/seed/floppy-messiah/400/600', status: 'In progress', rating: 7 },
  { key: 'children-of-dune', type: 'tv', title: 'Children of Dune', year: '2003', note: '3 episodes', image: 'https://picsum.photos/seed/floppy-children/400/600', status: 'Planning', rating: null },
  { key: 'dune-prophecy', type: 'tv', title: 'Dune: Prophecy', year: '2024', note: '6 episodes', image: 'https://picsum.photos/seed/floppy-prophecy/400/600', status: 'In progress', rating: 6 },
  { key: 'road-to-dune', type: 'book', title: 'The Road to Dune', year: '2005', note: 'Brian Herbert', image: 'https://picsum.photos/seed/floppy-road/400/600', status: null, rating: null },
  { key: 'dune-ost', type: 'music', title: 'Dune (Original Motion Picture Soundtrack)', year: '2021', note: 'Hans Zimmer', image: 'https://picsum.photos/seed/floppy-dune-ost/400/600', status: 'Completed', rating: 8 },
  { key: 'dune-sketchbook', type: 'music', title: 'The Dune Sketchbook', year: '2021', note: 'Hans Zimmer', image: 'https://picsum.photos/seed/floppy-sketchbook/400/600', status: 'In progress', rating: 7 },
];

const ONLINE_ITEMS = [
  { key: 'jodorowsky-dune', type: 'movie', title: "Jodorowsky's Dune", year: '2013', note: '1h 30m', image: 'https://picsum.photos/seed/floppy-jodorowsky/400/600', status: null, rating: null },
  { key: 'dreamer-dune', type: 'movie', title: 'The Dreamer of Dune', year: '2022', note: 'Documentary', image: 'https://picsum.photos/seed/floppy-dreamer/400/600', status: null, rating: null },
  { key: 'dune-companion', type: 'book', title: 'The Dune Companion', year: '2020', note: 'Reference', image: 'https://picsum.photos/seed/floppy-companion/400/600', status: null, rating: null },
  { key: 'sisterhood-dune', type: 'tv', title: 'Dune: The Sisterhood', year: '2024', note: '6 episodes', image: 'https://picsum.photos/seed/floppy-sisterhood/400/600', status: null, rating: null },
  { key: 'dune-two-ost', type: 'music', title: 'Dune: Part Two (Original Motion Picture Soundtrack)', year: '2024', note: 'Hans Zimmer', image: 'https://picsum.photos/seed/floppy-dune-two-ost/400/600', status: null, rating: null },
  { key: 'dune-prophecy-ost', type: 'music', title: 'Dune: Prophecy (Soundtrack)', year: '2024', note: 'Various artists', image: 'https://picsum.photos/seed/floppy-prophecy-ost/400/600', status: null, rating: null },
];

function demoModel(item, ratings) {
  const rated = ratings[item.key];
  return {
    mediaType: item.type,
    shape: 'poster',
    href: `/demo/${item.key}`,
    image: { src: item.image, fallback: '', source: 'primary' },
    title: item.title,
    altTitle: null,
    statusChip: item.status ? { kind: 'status', status: item.status, label: item.status } : null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: [{ join: 'plain', parts: [{ text: item.year }, { text: `• ${item.note}`, muted: true }] }],
    rating: item.rating == null && rated == null ? null : {
      label: String(rated ?? item.rating),
      value: rated ?? item.rating,
      scaleMax: 10,
      rateLabel: 'Rate',
    },
    ratingEditable: true,
    actions: null,
  };
}

function matches(item, needle, mediaType) {
  return (mediaType === 'all' || item.type === mediaType)
    && (!needle || item.title.toLowerCase().includes(needle));
}

export default function SearchResultsSlot({ query = 'dune', mediaType: initialMediaType = 'all', onOpenDetail }) {
  const [mediaType, setMediaType] = useState(initialMediaType || 'all');
  const [layout, setLayout] = useState('grid');
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [source, setSource] = useState(DEFAULT_SOURCE[initialMediaType] || null);
  const [page, setPage] = useState(1);
  const [visibleLocal, setVisibleLocal] = useState(2);
  const [loadingMore, setLoadingMore] = useState(false);
  const [status, setStatus] = useState('loading');
  const [request, setRequest] = useState(0);
  const [ratings, setRatings] = useState({});
  const loadTimer = useRef(null);
  const queryTimer = useRef(null);

  useEffect(() => {
    setMediaType(initialMediaType || 'all');
  }, [initialMediaType]);

  useEffect(() => {
    setSource(DEFAULT_SOURCE[mediaType] || null);
    setPage(1);
    setVisibleLocal(2);
    setOnlineOnly(false);
  }, [mediaType, query]);

  useEffect(() => () => {
    clearTimeout(loadTimer.current);
    clearTimeout(queryTimer.current);
  }, []);

  const sourceOptions = SOURCE_OPTIONS[mediaType] || [];
  const activeSource = sourceOptions.find(option => option.value === source) || sourceOptions[0] || null;

  useEffect(() => {
    setStatus('loading');
    clearTimeout(queryTimer.current);
    queryTimer.current = setTimeout(() => {
      setStatus(activeSource?.unavailable ? 'error' : 'ready');
    }, 350);
    return () => clearTimeout(queryTimer.current);
  }, [query, mediaType, source, request, activeSource?.unavailable]);

  const needle = String(query || '').trim().toLowerCase();
  const model = (item) => demoModel(item, ratings);

  const localMatches = LIBRARY_ITEMS.filter(item => matches(item, needle, mediaType));
  const onlineMatches = mediaType === 'all' ? [] : ONLINE_ITEMS.filter(item => matches(item, needle, mediaType));

  const pageSize = 2;
  const totalPages = Math.max(1, Math.ceil(onlineMatches.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const onlinePage = onlineMatches.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const sections = [];
  if (mediaType === 'all') {
    for (const type of ['movie', 'tv', 'book', 'music']) {
      const items = LIBRARY_ITEMS.filter(item => item.type === type && matches(item, needle, type));
      if (!items.length) continue;
      sections.push({
        key: type,
        title: TYPE_LABEL[type],
        totalLabel: `${items.length} results`,
        subsections: [{ key: type, items: items.map(model), layout }],
      });
    }
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
        totalLabel: `${onlineMatches.length} results`,
        subsections: [{ key: 'online', items: onlinePage.map(model), layout }],
      });
    }
  }

  const paging = onlineMatches.length ? {
    page: currentPage,
    totalPages,
    totalResults: onlineMatches.length,
    previous: currentPage > 1 ? { number: currentPage - 1 } : null,
    next: currentPage < totalPages ? { number: currentPage + 1 } : null,
    pages: Array.from({ length: totalPages }, (_, index) => ({
      number: index + 1,
      current: index + 1 === currentPage,
    })),
    summary: `Page ${currentPage} of ${totalPages} (${onlineMatches.length} results)`,
  } : null;

  const hasMore = mediaType !== 'all' && !onlineOnly && visibleLocal < localMatches.length;
  const viewState = status === 'loading' ? 'loading' : status === 'error' ? 'error' : sections.length ? 'ready' : 'empty';
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
      setVisibleLocal(current => current + 2);
      setLoadingMore(false);
    }, 450);
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
      title: 'No results found',
      body: `We couldn't find any matches for “${query}”. Try checking the spelling or using a different media type.`,
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
      const key = item?.href?.split('/').pop();
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
