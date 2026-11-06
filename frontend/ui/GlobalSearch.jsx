import React, { useEffect, useRef, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Spinner } from './Spinner';

const MIN_QUERY_LENGTH = 2;

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d1d5db',
  textMuted: '#adb5bd',
  panel: '#272c31',
  surface: '#2a2f35',
  surfaceMuted: '#343a40',
  surfaceAlt: '#3e454d',
  border: '#343a40',
  accent: '#4a9eff',
  errorSurface: '#2a2f35',
  errorBorder: '#4b5563',
  focusStyle: {},
  radius: 6,
  menuWidth: 128,
  inputHeight: 36,
  iconSize: 20,
  fontSize: 14,
};

const label = (value, fallback) => (
  typeof value === 'string' && value.length ? value : fallback
);

function fill(template, values) {
  return String(template).replace(/%\((\w+)\)s/g, (match, key) => (
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match
  ));
}

function SearchGlyph({ color, size = 18 }) {
  const ring = Math.round(size * 0.62);
  return <View aria-hidden style={{ width: size, height: size }}>
    <View style={{
      position: 'absolute',
      top: 1,
      left: 1,
      width: ring,
      height: ring,
      borderRadius: ring / 2,
      borderWidth: 2,
      borderColor: color,
    }} />
    <View style={{
      position: 'absolute',
      right: 1,
      bottom: 0,
      width: 2,
      height: Math.round(size * 0.34),
      backgroundColor: color,
      transform: [{ rotate: '-45deg' }],
    }} />
  </View>;
}

function CameraGlyph({ color, size = 18 }) {
  const bodyHeight = Math.round(size * 0.7);
  const lens = Math.round(size * 0.36);
  return <View aria-hidden style={{ width: size, height: size }}>
    <View style={{
      position: 'absolute',
      left: 1,
      bottom: 1,
      width: size - 2,
      height: bodyHeight,
      borderRadius: 3,
      borderWidth: 2,
      borderColor: color,
    }} />
    <View style={{
      position: 'absolute',
      top: 0,
      left: Math.round(size * 0.28),
      width: Math.round(size * 0.3),
      height: 3,
      borderTopLeftRadius: 2,
      borderTopRightRadius: 2,
      backgroundColor: color,
    }} />
    <View style={{
      position: 'absolute',
      left: Math.round((size - lens) / 2),
      bottom: Math.round((bodyHeight - lens) / 2) + 1,
      width: lens,
      height: lens,
      borderRadius: lens / 2,
      borderWidth: 2,
      borderColor: color,
    }} />
  </View>;
}

function Chevron({ color, size = 14 }) {
  return <View aria-hidden style={{
    width: size * 0.55,
    height: size * 0.55,
    borderRightWidth: 2,
    borderBottomWidth: 2,
    borderColor: color,
    transform: [{ rotate: '45deg' }],
    marginTop: -3,
  }} />;
}

export function GlobalSearch({
  query: initialQuery = '',
  selectedType,
  mediaTypes = [],
  barcodeTypes = [],
  labels = {},
  palette: paletteOverrides,
  compact = false,
  expanded = false,
  dismissSignal = 0,
  onLoadSuggestions,
  onSubmit,
  onSelectSuggestion,
  onBarcodeRequest,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const [query, setQuery] = useState(initialQuery);
  const [userTyped, setUserTyped] = useState(false);
  const [type, setType] = useState(selectedType || mediaTypes[0] || { display: 'All', value: 'all' });
  const [menuOpen, setMenuOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [panel, setPanel] = useState({ status: 'idle', suggestions: [] });
  const [barcodeBusy, setBarcodeBusy] = useState(false);
  const [barcodeError, setBarcodeError] = useState(null);
  const loader = useRef(onLoadSuggestions);
  const trimmed = query.trim();
  const isBarcodeType = barcodeTypes.includes(type.value);

  useEffect(() => { loader.current = onLoadSuggestions; }, [onLoadSuggestions]);
  useEffect(() => { setQuery(initialQuery || ''); setUserTyped(false); }, [initialQuery]);
  useEffect(() => {
    setMenuOpen(false);
    setPanel({ status: 'idle', suggestions: [] });
    setActiveIndex(-1);
  }, [dismissSignal]);

  useEffect(() => {
    setActiveIndex(-1);
    if (!userTyped || trimmed.length < MIN_QUERY_LENGTH || !loader.current) {
      setPanel({ status: 'idle', suggestions: [] });
      return undefined;
    }
    let cancelled = false;
    setPanel({ status: 'loading', suggestions: [] });
    const timer = setTimeout(() => {
      Promise.resolve()
        .then(() => loader.current({ query: trimmed, mediaType: type.value }))
        .then(result => {
          if (cancelled) return;
          const suggestions = Array.isArray(result?.suggestions) ? result.suggestions : [];
          setPanel({ status: suggestions.length ? 'ready' : 'empty', suggestions });
        })
        .catch(() => {
          if (!cancelled) setPanel({ status: 'error', suggestions: [] });
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [trimmed, type.value, userTyped]);

  const footerOption = panel.status === 'ready' && panel.suggestions.length
    ? {
      key: 'online',
      id: 'global-search-suggestion-online',
      kind: 'footer',
      label: type.value === 'all'
        ? fill(label(labels.suggestionsSeeAll, 'See all library results for “%(query)s”'), { query: trimmed })
        : fill(label(labels.suggestionsSearchOnline, 'Search online for “%(query)s”'), { query: trimmed }),
    }
    : null;
  const suggestionOptions = panel.status === 'ready'
    ? panel.suggestions.map((suggestion, index) => ({
      key: suggestion.id ?? `${index}`,
      id: `global-search-suggestion-${suggestion.id ?? index}`,
      kind: 'suggestion',
      suggestion,
    }))
    : [];
  const options = footerOption ? [...suggestionOptions, footerOption] : suggestionOptions;
  const activeOption = activeIndex >= 0 ? options[activeIndex] : null;

  function placeholder() {
    if (type.value === 'all') return label(labels.placeholderAll, 'Search your whole library...');
    const template = compact
      ? label(labels.placeholderShort, 'Search %(media)s...')
      : label(labels.placeholderLong, 'Search %(media)s in your library or online...');
    return fill(template, { media: type.display });
  }

  function clearPanel() {
    setPanel({ status: 'idle', suggestions: [] });
    setActiveIndex(-1);
  }

  function submit(value = query, mediaType = type.value) {
    const next = String(value || '').trim();
    if (!next) return;
    clearPanel();
    onSubmit?.({ query: next, mediaType });
  }

  function choose(option) {
    if (!option) return;
    if (option.kind === 'footer') {
      submit();
      return;
    }
    clearPanel();
    onSelectSuggestion?.(option.suggestion);
  }

  function selectType(next) {
    setType(next);
    setMenuOpen(false);
    setActiveIndex(-1);
    if (trimmed) submit(query, next.value);
  }

  function handleKeyPress(event) {
    const key = event?.nativeEvent?.key ?? event?.key;
    if (key === 'ArrowDown') {
      if (!options.length) return;
      event.preventDefault?.();
      setActiveIndex(current => Math.min(current + 1, options.length - 1));
    } else if (key === 'ArrowUp') {
      if (!options.length) return;
      event.preventDefault?.();
      setActiveIndex(current => Math.max(current - 1, -1));
    } else if (key === 'Escape') {
      if (options.length || panel.status !== 'idle') {
        event.preventDefault?.();
        clearPanel();
      } else if (menuOpen) {
        event.preventDefault?.();
        setMenuOpen(false);
      }
    }
  }

  function handleSubmitEditing() {
    if (activeOption) choose(activeOption);
    else submit();
  }

  async function requestBarcode() {
    if (!onBarcodeRequest || barcodeBusy) return;
    setBarcodeBusy(true);
    setBarcodeError(null);
    try {
      const result = await onBarcodeRequest();
      if (!result || result.status === 'cancelled') return;
      if (result.status === 'decoded' && result.isbn) {
        setQuery(result.isbn);
        submit(result.isbn);
      } else if (result.status === 'unavailable') {
        setBarcodeError(label(labels.barcodeUnavailable, 'Barcode scanning is not available on this device. Enter an ISBN instead.'));
      } else {
        setBarcodeError(label(labels.barcodeUnreadable, 'Could not read barcode from image. Please try again or enter ISBN manually.'));
      }
    } catch (error) {
      setBarcodeError(label(labels.barcodeFailed, 'Error scanning barcode: ')
        + (error?.message || label(labels.tryAgain, 'Please try again.')));
    } finally {
      setBarcodeBusy(false);
    }
  }

  function dismissBarcodeError() {
    setBarcodeError(null);
  }

  const showPanel = panel.status !== 'idle';

  return <View style={[styles.root, expanded && styles.expanded]}>
    <View style={styles.row}>
      <View style={styles.inputWrap}>
        <Pressable accessibilityRole="button" accessibilityLabel={label(labels.search, 'Search')}
          onPress={() => submit()} style={styles.searchButton}>
          <SearchGlyph color={palette.textMuted} size={palette.iconSize} />
        </Pressable>
        <TextInput
          nativeID="global-search"
          accessibilityLabel={label(labels.inputLabel, 'Search your library or online')}
          value={query}
          onChangeText={value => { setUserTyped(true); setQuery(value); }}
          placeholder={placeholder()}
          placeholderTextColor={palette.textMuted}
          autoComplete="off"
          autoCorrect={false}
          autoCapitalize="none"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={options.length > 0}
          aria-controls="global-search-suggestions"
          aria-activedescendant={activeOption?.id}
          returnKeyType="search"
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyPress={handleKeyPress}
          onSubmitEditing={handleSubmitEditing}
          style={[
            styles.input,
            {
              color: palette.textSecondary,
              backgroundColor: palette.panel,
              borderTopLeftRadius: palette.radius,
              borderBottomLeftRadius: palette.radius,
              paddingRight: isBarcodeType ? 40 : 16,
              outlineStyle: focused ? 'solid' : 'none',
              outlineWidth: focused ? 2 : 0,
              outlineColor: palette.accent,
              outlineOffset: -2,
            },
            focused && palette.focusStyle,
          ]}
        />
        {isBarcodeType ? <Pressable accessibilityRole="button"
          accessibilityLabel={label(labels.scan, 'Scan barcode')}
          accessibilityState={{ disabled: barcodeBusy }}
          disabled={barcodeBusy}
          onPress={requestBarcode}
          style={[styles.barcodeButton, barcodeBusy && styles.disabled]}>
          {barcodeBusy
            ? <Spinner size={20} color={palette.textMuted} />
            : <CameraGlyph color={palette.textMuted} size={palette.iconSize} />}
        </Pressable> : null}
        {showPanel ? <View nativeID="global-search-suggestions" role="listbox"
          accessibilityLabel={label(labels.suggestions, 'Search suggestions')}
          style={{
            position: 'absolute',
            top: palette.inputHeight,
            left: 0,
            right: 0,
            zIndex: 50,
            marginTop: 4,
            maxHeight: 240,
            borderWidth: 1,
            borderColor: palette.border,
            borderRadius: palette.radius,
            backgroundColor: palette.surface,
            elevation: 8,
            shadowColor: '#000',
            shadowOpacity: 0.25,
            shadowRadius: 12,
            shadowOffset: { width: 0, height: 6 },
          }}>
          <ScrollView keyboardShouldPersistTaps="handled" nestedScrollEnabled>
            {panel.status === 'loading' ? <View style={styles.stateRow}>
              <Spinner size={16} color={palette.textMuted} />
              <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>
                {label(labels.suggestionsLoading, 'Loading suggestions…')}
              </Text>
            </View> : null}
            {panel.status === 'error' ? <View style={styles.stateRow}>
              <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>
                {label(labels.suggestionsError, 'Suggestions could not load. Keep typing or press Enter.')}
              </Text>
            </View> : null}
            {panel.status === 'empty' ? <View style={styles.stateRow}>
              <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>
                {type.value === 'all'
                  ? fill(label(labels.suggestionsEmptyAll, 'Nothing in your library matches “%(query)s”. Pick a media type to search online.'), { query: trimmed })
                  : fill(label(labels.suggestionsEmptyType, 'Nothing saved matches “%(query)s”. Keep typing and press Enter to search online.'), { query: trimmed })}
              </Text>
            </View> : null}
            {options.map((option, index) => {
              const isActive = index === activeIndex;
              if (option.kind === 'footer') {
                return <Pressable key={option.key} nativeID={option.id}
                  role="option" aria-selected={isActive}
                  accessibilityRole="button"
                  accessibilityLabel={option.label}
                  onPress={() => choose(option)}
                  style={({ hovered }) => [styles.footerRow,
                    { borderTopColor: palette.border },
                    (hovered || isActive) && { backgroundColor: palette.surfaceMuted }]}>
                  <SearchGlyph color={palette.textMuted} size={14} />
                  <Text numberOfLines={1} style={[styles.footerText, { color: palette.textMuted }]}>{option.label}</Text>
                  <Text style={[styles.keycap, { color: palette.textMuted, borderColor: palette.border }]}>Enter</Text>
                </Pressable>;
              }
              const suggestion = option.suggestion;
              return <Pressable key={option.key} nativeID={option.id}
                role="option" aria-selected={isActive}
                accessibilityRole="link"
                accessibilityLabel={[suggestion.title, suggestion.subtitle].filter(Boolean).join(', ')}
                onPress={() => choose(option)}
                style={({ hovered, pressed }) => [styles.option,
                  (hovered || pressed || isActive) && { backgroundColor: palette.surfaceMuted }]}>
                {suggestion.image
                  ? <Image accessible={false} source={{ uri: suggestion.image }}
                    resizeMode="cover" style={[styles.thumb, { backgroundColor: palette.surfaceAlt }]} />
                  : <View style={[styles.thumb, styles.thumbFallback, { backgroundColor: palette.surfaceAlt }]}>
                    <SearchGlyph color={palette.textMuted} size={14} />
                  </View>}
                <View style={styles.optionText}>
                  <Text numberOfLines={1} style={[styles.optionTitle, { color: palette.textSecondary }]}>{suggestion.title}</Text>
                  {suggestion.subtitle ? <Text numberOfLines={1}
                    style={[styles.optionSubtitle, { color: palette.textMuted }]}>{suggestion.subtitle}</Text> : null}
                </View>
              </Pressable>;
            })}
          </ScrollView>
        </View> : null}
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={type.display}
        aria-haspopup="listbox" aria-expanded={menuOpen}
        onPress={() => setMenuOpen(open => !open)}
        style={({ hovered, pressed }) => [styles.typeButton, {
          backgroundColor: (hovered || pressed) ? palette.surface : palette.panel,
          borderTopRightRadius: palette.radius,
          borderBottomRightRadius: palette.radius,
        }]}>
        <Text numberOfLines={1} style={[styles.typeText, { color: palette.textSecondary }]}>{type.display}</Text>
        <Chevron color={palette.textMuted} size={14} />
      </Pressable>
      {menuOpen ? <View style={[styles.menu, {
        width: palette.menuWidth,
        backgroundColor: palette.surface,
        borderColor: palette.border,
        borderRadius: palette.radius,
      }]}>
        {mediaTypes.map(option => <Pressable key={option.value}
          accessibilityRole="button" accessibilityLabel={option.display}
          onPress={() => selectType(option)}
          style={({ hovered, pressed }) => [styles.menuItem,
            (hovered || pressed || option.value === type.value) && { backgroundColor: palette.surfaceMuted }]}>
          <Text numberOfLines={1} style={[styles.menuText, { color: palette.textSecondary }]}>{option.display}</Text>
        </Pressable>)}
      </View> : null}
    </View>
    {barcodeError ? <View style={[styles.toast, {
      backgroundColor: palette.errorSurface,
      borderColor: palette.errorBorder,
      borderRadius: palette.radius,
    }]}>
      <Text accessibilityLiveRegion="polite" role="alert"
        style={[styles.toastText, { color: palette.textSecondary }]}>{barcodeError}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={label(labels.dismiss, 'Dismiss error')}
        onPress={dismissBarcodeError} style={styles.toastDismiss}>
        <Text aria-hidden style={[styles.toastClose, { color: palette.textMuted }]}>×</Text>
      </Pressable>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { position: 'relative', zIndex: 30, maxWidth: 672 },
  expanded: { width: '100%', maxWidth: undefined },
  row: { flexDirection: 'row', alignItems: 'stretch', position: 'relative' },
  inputWrap: { flex: 1, minWidth: 0, position: 'relative' },
  input: { minHeight: 36, paddingTop: 8, paddingBottom: 8, paddingLeft: 40, fontSize: 14 },
  searchButton: { position: 'absolute', left: 8, top: 0, bottom: 0, zIndex: 2, justifyContent: 'center' },
  barcodeButton: { position: 'absolute', right: 8, top: 0, bottom: 0, zIndex: 2, justifyContent: 'center' },
  disabled: { opacity: 0.5 },
  typeButton: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16, paddingVertical: 8 },
  typeText: { fontSize: 14, flexShrink: 1 },
  menu: { position: 'absolute', top: 48, right: 0, zIndex: 60, borderWidth: 1, paddingVertical: 4, elevation: 6, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
  menuItem: { paddingHorizontal: 16, paddingVertical: 8 },
  menuText: { fontSize: 14 },
  option: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 8 },
  optionText: { flex: 1, minWidth: 0 },
  optionTitle: { fontSize: 14 },
  optionSubtitle: { fontSize: 12, marginTop: 1 },
  thumb: { width: 32, height: 40, borderRadius: 4, flexShrink: 0 },
  thumbFallback: { alignItems: 'center', justifyContent: 'center' },
  footerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 8, borderTopWidth: 1 },
  footerText: { flex: 1, minWidth: 0, fontSize: 12 },
  keycap: { fontSize: 11, borderWidth: 1, borderRadius: 3, paddingHorizontal: 6, paddingVertical: 1 },
  stateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 12 },
  stateText: { flex: 1, fontSize: 14, lineHeight: 20 },
  toast: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8, marginTop: 8, maxWidth: 672, elevation: 6, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
  toastText: { flex: 1, fontSize: 13, fontWeight: '500' },
  toastDismiss: { padding: 2 },
  toastClose: { fontSize: 18, lineHeight: 18 },
});
