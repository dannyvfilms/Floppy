import React, { useMemo, useState } from 'react';
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

const DEMO_ITEMS = [
  { key: 'dune', type: 'movie', title: 'Dune', year: '2021', note: '2h 35m', image: 'https://picsum.photos/seed/floppy-dune/400/600', status: 'Completed', rating: 9 },
  { key: 'dune-two', type: 'movie', title: 'Dune: Part Two', year: '2024', note: '2h 46m', image: 'https://picsum.photos/seed/floppy-dune-two/400/600', status: 'Completed', rating: 9 },
  { key: 'dune-messiah', type: 'book', title: 'Dune Messiah', year: '1969', note: 'Frank Herbert', image: 'https://picsum.photos/seed/floppy-messiah/400/600', status: 'In progress', rating: 7 },
  { key: 'children-of-dune', type: 'tv', title: 'Children of Dune', year: '2003', note: '3 episodes', image: 'https://picsum.photos/seed/floppy-children/400/600', status: 'Planning', rating: null },
  { key: 'dune-prophecy', type: 'tv', title: 'Dune: Prophecy', year: '2024', note: '6 episodes', image: 'https://picsum.photos/seed/floppy-prophecy/400/600', status: 'In progress', rating: 6 },
  { key: 'road-to-dune', type: 'book', title: 'The Road to Dune', year: '2005', note: 'Brian Herbert', image: 'https://picsum.photos/seed/floppy-road/400/600', status: null, rating: null },
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

const MEDIA_SCOPE = [
  { value: 'all', label: 'All' },
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'TV' },
  { value: 'book', label: 'Books' },
];

const EXTRA_ITEMS = [
  { key: 'dune-companion', type: 'book', title: 'The Dune Companion', year: '2020', note: 'Reference', image: 'https://picsum.photos/seed/floppy-companion/400/600', status: null, rating: null },
  { key: 'jodorowsky-dune', type: 'movie', title: "Jodorowsky's Dune", year: '2013', note: '1h 30m', image: 'https://picsum.photos/seed/floppy-jodorowsky/400/600', status: null, rating: null },
  { key: 'dreamer-dune', type: 'tv', title: 'The Dreamer of Dune', year: '2022', note: 'Documentary', image: 'https://picsum.photos/seed/floppy-dreamer/400/600', status: null, rating: null },
];

export default function SearchResultsSlot({ query = 'dune', mediaType: initialMediaType = 'all', onOpenDetail }) {
  const [mediaType, setMediaType] = useState(initialMediaType || 'all');
  const [layout, setLayout] = useState('grid');
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [extra, setExtra] = useState([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [ratings, setRatings] = useState({});

  const filtered = useMemo(() => {
    const needle = String(query || '').trim().toLowerCase();
    return DEMO_ITEMS
      .filter(item => mediaType === 'all' || item.type === mediaType)
      .filter(item => !needle || item.title.toLowerCase().includes(needle));
  }, [query, mediaType]);

  const all = [...filtered, ...extra.filter(item => mediaType === 'all' || item.type === mediaType)];
  const local = all.slice(0, 3);
  const online = all.slice(3);

  const sections = [];
  if (!onlineOnly && local.length) {
    sections.push({
      key: 'local',
      title: 'In Your Library',
      totalLabel: `${local.length} results`,
      searchOnline: { label: 'Search online' },
      subsections: [{ key: 'local', items: local.map(item => demoModel(item, ratings)), layout }],
    });
  }
  if (online.length) {
    sections.push({
      key: 'online',
      title: 'Online Results',
      totalLabel: `${online.length} results`,
      subsections: [{ key: 'online', items: online.map(item => demoModel(item, ratings)), layout }],
    });
  }

  const hasMore = filtered.length > 0 && extra.length < EXTRA_ITEMS.length;

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    setTimeout(() => {
      setExtra(current => [...current, ...EXTRA_ITEMS.slice(current.length, current.length + 2)]);
      setLoadingMore(false);
    }, 500);
  }

  function selectScope(option) {
    setMediaType(option.value);
    setOnlineOnly(false);
  }

  return <SearchResults
    title={query ? `Search results for “${query}”` : 'Search Results'}
    state={all.length ? 'ready' : 'empty'}
    labels={labels}
    palette={searchPalette}
    scope={{
      label: '',
      options: MEDIA_SCOPE.map(option => ({ ...option, active: option.value === mediaType })),
    }}
    layoutOptions={[
      { value: 'grid', label: 'Grid View', glyph: '▦', active: layout === 'grid' },
      { value: 'list', label: 'List View', glyph: '☰', active: layout === 'list' },
    ]}
    notes={onlineOnly ? [`Showing online results for “${query}”.`] : []}
    sections={sections}
    hasMore={hasMore}
    loadingMore={loadingMore}
    empty={{
      title: 'No results found',
      body: `We couldn't find any matches for “${query}”. Try checking the spelling or using a different media type.`,
    }}
    onSelectScope={selectScope}
    onSelectLayout={option => setLayout(option.value)}
    onSearchOnline={() => setOnlineOnly(true)}
    onOpenResult={href => onOpenDetail?.(href)}
    onLoadMore={loadMore}
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
