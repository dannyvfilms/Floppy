import React, { useCallback, useRef, useState } from 'react';
import { Platform, useWindowDimensions } from 'react-native';
import { GlobalSearch } from '../../../frontend/ui/GlobalSearch.jsx';
import { BarcodeScannerModal } from '../components/BarcodeScannerModal';
import { createSearchTransport, localResultsFromPayload } from '../data/searchTransport';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SEARCH',
  title: 'Global search and suggestions',
  where: 'Header on Home, Discover and Library, and the Search screen',
  status: 'in_progress',
  note: 'The shared React Native search field renders here with the media-type menu, two-character suggestions, the search-all/search-online footer, loading/empty/error rows and the search, suggestion and barcode callbacks. Book, Manga, Comic and Comic Issue scopes open the Expo camera/photo/manual-ISBN sheet. Signed-in suggestions query /api/v1/media/?search= through the session facade; signed-out keeps the sample rows. The web adapter keeps the GET search action and JSON suggestion endpoint. Expo export is compile-only evidence: camera, photo, permission, manual-ISBN, suggestion, menu and screen-reader interaction were not exercised on iOS or Android.',
};

const mediaTypes = [
  { display: 'All', value: 'all' },
  { display: 'TV Shows', value: 'tv' },
  { display: 'Movies', value: 'movie' },
  { display: 'Anime', value: 'anime' },
  { display: 'Manga', value: 'manga' },
  { display: 'Games', value: 'game' },
  { display: 'Books', value: 'book' },
  { display: 'Comics', value: 'comic' },
  { display: 'Board Games', value: 'boardgame' },
  { display: 'Music', value: 'music' },
  { display: 'Podcasts', value: 'podcast' },
  { display: 'Videos', value: 'video' },
];

const library = [
  { title: 'Dune', subtitle: 'Movie · 2021', type: 'movie' },
  { title: 'Dune: Part Two', subtitle: 'Movie · 2024', type: 'movie' },
  { title: 'Dune Messiah', subtitle: 'Book · Frank Herbert', type: 'book' },
  { title: 'The Bear', subtitle: 'TV Show · In progress', type: 'tv' },
  { title: 'Blue Eye Samurai', subtitle: 'Anime · Completed', type: 'anime' },
  { title: 'Vinland Saga', subtitle: 'Manga · Makoto Yukimura', type: 'manga' },
  { title: 'Hades', subtitle: 'Game · 12 hours played', type: 'game' },
  { title: 'Saga #1', subtitle: 'Comic Issue · Brian K. Vaughan', type: 'comicissue' },
  { title: 'Wingspan', subtitle: 'Board Game · 4 plays', type: 'boardgame' },
  { title: 'Piranesi', subtitle: 'Book · Susanna Clarke', type: 'book' },
  { title: 'The Last of Us', subtitle: 'TV Show · Planning', type: 'tv' },
  { title: 'Every Frame a Painting', subtitle: 'Video · Essay', type: 'video' },
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
  barcodeUnavailable: 'Barcode scanning is not available on this device. Enter an ISBN instead.',
  barcodeUnreadable: 'Could not read a barcode from that image. Try again or type the ISBN.',
  barcodeFailed: 'Error scanning barcode: ',
  tryAgain: 'Please try again.',
  barcodeTitle: 'Scan a book barcode',
  barcodeHelp: 'Point the camera at the ISBN barcode, or choose a photo. You can also type the ISBN.',
  barcodePermissionTitle: 'Camera access needed',
  barcodePermissionBody: 'Allow camera access to scan the barcode, or choose a photo or type the ISBN below.',
  barcodeAllowCamera: 'Allow camera',
  barcodeOpenSettings: 'Open Settings',
  barcodeChoosePhoto: 'Choose photo',
  barcodeManualLabel: 'ISBN',
  barcodeManualPlaceholder: 'Type an ISBN-10 or ISBN-13',
  barcodeManualAction: 'Use ISBN',
  barcodeCancel: 'Cancel',
  barcodeChecking: 'Reading barcode…',
  barcodeInvalidManual: 'Enter a valid ISBN-10 or ISBN-13.',
  barcodeNotIsbn: 'That barcode is not an ISBN. Try a book barcode.',
  barcodePhotoUnreadable: 'Could not read a barcode from that photo. Try again or type the ISBN.',
  barcodeCameraError: 'The camera could not start. Choose a photo or type the ISBN.',
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
  focusStyle: Platform.OS === 'ios' ? { outlineColor: 'transparent' } : {},
  ...(Platform.OS === 'ios' ? { inputHeight: 44, searchTouchWidth: 44 } : {}),
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
  const { width } = useWindowDimensions();
  const [transport] = useState(() => createSearchTransport());
  const compact = width < 640;
  const selectedType = mediaTypes.find(option => option.value === initialMediaType) || mediaTypes[0];
  const [scannerVisible, setScannerVisible] = useState(false);
  const pendingBarcode = useRef(null);

  const requestBarcode = useCallback(() => new Promise(resolve => {
    pendingBarcode.current = resolve;
    setScannerVisible(true);
  }), []);

  const closeScanner = useCallback((result) => {
    const resolve = pendingBarcode.current;
    pendingBarcode.current = null;
    setScannerVisible(false);
    resolve?.(result);
  }, []);

  const loadSuggestions = useCallback(async ({ query, mediaType }) => {
    await wait(180);
    if (transport.mode === 'server') {
      const payload = await transport.searchLocal({ search: query, mediaType, limit: 8, offset: 0 });
      return {
        suggestions: localResultsFromPayload(payload).slice(0, 8).map((item, index) => ({
          ...item,
          id: `${item.type}-${index}`,
          title: item.title,
          subtitle: [item.note, item.year, item.status].filter(Boolean).join(' · '),
          mediaType: item.type,
        })),
      };
    }
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
          mediaType: item.type,
        })),
    };
  }, [transport]);

  function openSuggestion(suggestion) {
    if (onOpenSuggestion) onOpenSuggestion(suggestion);
    else onOpenSearch?.({ query: suggestion.title, mediaType: suggestion.mediaType || initialMediaType });
  }

  return <>
    <GlobalSearch
      expanded={expanded}
      compact={compact}
      query={initialQuery}
      selectedType={selectedType}
      mediaTypes={mediaTypes}
      barcodeTypes={['all', 'book', 'manga', 'comic', 'comicissue']}
      labels={labels}
      palette={searchPalette}
      onLoadSuggestions={loadSuggestions}
      onSubmit={onSubmit || onOpenSearch}
      onSelectSuggestion={openSuggestion}
      onBarcodeRequest={requestBarcode}
    />
    <BarcodeScannerModal
      visible={scannerVisible}
      labels={{
        title: labels.barcodeTitle,
        help: labels.barcodeHelp,
        cameraPermissionTitle: labels.barcodePermissionTitle,
        cameraPermissionBody: labels.barcodePermissionBody,
        allowCamera: labels.barcodeAllowCamera,
        openSettings: labels.barcodeOpenSettings,
        choosePhoto: labels.barcodeChoosePhoto,
        manualLabel: labels.barcodeManualLabel,
        manualPlaceholder: labels.barcodeManualPlaceholder,
        manualAction: labels.barcodeManualAction,
        cancel: labels.barcodeCancel,
        checking: labels.barcodeChecking,
        invalidManual: labels.barcodeInvalidManual,
        notIsbn: labels.barcodeNotIsbn,
        unreadable: labels.barcodePhotoUnreadable,
        cameraError: labels.barcodeCameraError,
      }}
      onCancel={() => closeScanner({ status: 'cancelled' })}
      onDecoded={isbn => closeScanner({ status: 'decoded', isbn })}
    />
  </>;
}
