import React, { useCallback } from 'react';
import { GlobalSearch } from '../../../frontend/ui/GlobalSearch';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SEARCH',
  title: 'Global search and suggestions',
  where: 'Header on Home, Discover and Library, and the Search screen',
  status: 'ported',
  note: 'The shared search field, media-type menu, suggestion list, barcode entry point and result links render here; the Search screen composes the shared results surface underneath.',
};

const mediaTypes = [
  { display: 'All', value: 'all' },
  { display: 'Movies', value: 'movie' },
  { display: 'TV Shows', value: 'tv' },
  { display: 'Anime', value: 'anime' },
  { display: 'Books', value: 'book' },
  { display: 'Comics', value: 'comic' },
  { display: 'Games', value: 'game' },
  { display: 'Music', value: 'music' },
  { display: 'Podcasts', value: 'podcast' },
];

const library = [
  { title: 'Dune', subtitle: 'Movie · 2021', type: 'movie' },
  { title: 'Dune: Part Two', subtitle: 'Movie · 2024', type: 'movie' },
  { title: 'Dune Messiah', subtitle: 'Book · Frank Herbert', type: 'book' },
  { title: 'The Bear', subtitle: 'TV Show · In progress', type: 'tv' },
  { title: 'Blue Eye Samurai', subtitle: 'Anime · Completed', type: 'anime' },
  { title: 'Hades', subtitle: 'Game · 12 hours played', type: 'game' },
  { title: 'Piranesi', subtitle: 'Book · Susanna Clarke', type: 'book' },
  { title: 'The Last of Us', subtitle: 'TV Show · Planning', type: 'tv' },
];

const labels = {
  inputLabel: 'Search your library or online',
  search: 'Search',
  scan: 'Scan barcode',
  dismiss: 'Dismiss error',
  placeholderAll: 'Search your whole library...',
  placeholderShort: 'Search %(media)s...',
  placeholderLong: 'Search %(media)s in your library or online...',
  suggestions: 'Search suggestions',
  suggestionsLoading: 'Loading suggestions…',
  suggestionsError: 'Suggestions could not load. Keep typing or press Enter.',
  suggestionsSeeAll: 'See all library results for “%(query)s”',
  suggestionsSearchOnline: 'Search online for “%(query)s”',
  suggestionsEmptyAll: 'Nothing in your library matches “%(query)s”. Pick a media type to search online.',
  suggestionsEmptyType: 'Nothing saved matches “%(query)s”. Keep typing and press Enter to search online.',
  barcodeUnavailable: 'Camera barcode scanning is not wired in this preview. Enter an ISBN instead.',
};

const searchPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  panel: palette.surface,
  surface: palette.surface,
  surfaceMuted: palette.surfaceStrong,
  surfaceAlt: palette.surfaceStrong,
  border: palette.border,
  accent: palette.accent,
  errorSurface: palette.surface,
  errorBorder: palette.surfaceMuted,
  radius: radius.sm,
};

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

export default function SearchSlot({
  expanded = false,
  initialQuery = '',
  initialMediaType = 'all',
  onOpenSearch,
  onOpenSuggestion,
  onSubmit,
}) {
  const selectedType = mediaTypes.find(option => option.value === initialMediaType) || mediaTypes[0];
  const loadSuggestions = useCallback(async ({ query, mediaType }) => {
    await wait(180);
    const needle = query.toLowerCase();
    return {
      suggestions: library
        .filter(item => mediaType === 'all' || item.type === mediaType)
        .filter(item => item.title.toLowerCase().includes(needle))
        .slice(0, 8)
        .map((item, index) => ({
          id: `${item.type}-${index}`,
          title: item.title,
          subtitle: item.subtitle,
        })),
    };
  }, []);

  function openSuggestion(suggestion) {
    if (onOpenSuggestion) onOpenSuggestion(suggestion);
    else onOpenSearch?.({ query: suggestion.title, mediaType: initialMediaType });
  }

  return <GlobalSearch
    expanded={expanded}
    query={initialQuery}
    selectedType={selectedType}
    mediaTypes={mediaTypes}
    barcodeTypes={['book', 'manga', 'comic', 'comicissue']}
    labels={labels}
    palette={searchPalette}
    onLoadSuggestions={loadSuggestions}
    onSubmit={onSubmit || onOpenSearch}
    onSelectSuggestion={openSuggestion}
    onBarcodeRequest={async () => ({ status: 'unavailable' })}
  />;
}
