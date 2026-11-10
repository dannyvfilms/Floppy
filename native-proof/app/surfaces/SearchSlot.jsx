import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Platform, useWindowDimensions } from 'react-native';
import { GlobalSearch } from '../../../frontend/ui/GlobalSearch.jsx';
import { BarcodeScannerModal } from '../components/BarcodeScannerModal';
import { createSearchTransport, searchBarFromPayload, suggestionsFromPayload } from '../data/searchTransport';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SEARCH',
  title: 'Global search and suggestions',
  where: 'Header on Home, Discover and Library, and the Search screen',
  status: 'in_progress',
  note: 'The shared React Native search field renders here with the media-type menu, barcode types and copy from /api/v1/search/sources/, two-character suggestions from /api/v1/search/suggestions/ (saved titles, collected and tagged items, matched titles), the search-all/search-online footer, loading/empty/error rows and the search, suggestion and barcode callbacks. Book, Manga, Comic and Comic Issue scopes open the Expo camera/photo/manual-ISBN sheet. Signed out, the menu offers All only and suggestions are empty; there is no sample content. Camera, photo, permission, manual-ISBN, suggestion, menu and screen-reader interaction were not exercised on iOS or Android.',
};

const ALL_TYPE = { display: 'All', value: 'all' };

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
  barcodeUnreadable: 'Could not read barcode from image. Please try again or enter ISBN manually.',
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
  barcodePhotoUnreadable: 'Could not read barcode from image. Please try again or enter ISBN manually.',
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

export default function SearchSlot({
  expanded = false,
  initialQuery = '',
  initialMediaType = 'all',
  onOpenSearch,
  onOpenSuggestion,
  onSubmit,
  dismissSignal = 0,
}) {
  const { width } = useWindowDimensions();
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => createSearchTransport(session ? { auth: session } : {}),
    [session],
  );
  const compact = width < 640;
  const [bar, setBar] = useState({ mediaTypes: [ALL_TYPE], barcodeTypes: [], labels: {} });
  const [scannerVisible, setScannerVisible] = useState(false);
  const pendingBarcode = useRef(null);

  // The type menu, barcode types and field copy come from the server, so the
  // user's enabled media types decide what is offered.
  useEffect(() => {
    if (transport.mode !== 'server') {
      setBar({ mediaTypes: [ALL_TYPE], barcodeTypes: [], labels: {} });
      return undefined;
    }
    let active = true;
    transport.loadSources({ mediaType: initialMediaType }).then(payload => {
      if (active) setBar(searchBarFromPayload(payload));
    }).catch(() => {});
    return () => { active = false; };
  }, [transport, initialMediaType]);

  const mediaTypes = bar.mediaTypes.length ? bar.mediaTypes : [ALL_TYPE];
  const selectedType = mediaTypes.find(option => option.value === initialMediaType) || mediaTypes[0];
  const fieldLabels = { ...labels, ...bar.labels };

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
    if (transport.mode !== 'server') return { suggestions: [] };
    const payload = await transport.loadSuggestions({ query, mediaType });
    return { suggestions: suggestionsFromPayload(payload) };
  }, [transport]);

  function openSuggestion(suggestion) {
    if (onOpenSuggestion) onOpenSuggestion(suggestion);
    else onOpenSearch?.({ query: suggestion.title, mediaType: suggestion.mediaType || initialMediaType });
  }

  return <>
    <GlobalSearch
      // The field keeps its own selected type, so it restarts when the page's
      // type changes or the server's type list arrives.
      key={`${selectedType.value}:${mediaTypes.length}`}
      expanded={expanded}
      dismissSignal={dismissSignal}
      compact={compact}
      query={initialQuery}
      selectedType={selectedType}
      mediaTypes={mediaTypes}
      barcodeTypes={bar.barcodeTypes}
      labels={fieldLabels}
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
