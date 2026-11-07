import React, { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';
import { CatalogCard, CatalogGrid } from '../ui/controls/Catalog';
import { FilterDropdown } from '../ui/controls/Menu';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  success: '#10b981',
  warning: '#f59e0b',
  card: '#27272a',
  cardHovered: '#3f3f46',
  cardPressed: '#3f3f46',
  focus: '#818cf8',
  statusNeutral: '#a1a1aa',
  statusSuccess: '#10b981',
  statusWarning: '#f59e0b',
  attention: '#fbbf24',
  pin: '#a1a1aa',
  pinActive: '#818cf8',
  radius: 6,
};

const DEFAULT_BUTTON_PALETTE = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const DEFAULT_LABELS = {
  providers: 'Providers',
  setup: 'Run guided setup',
  description: 'Find services and their available settings.',
  searchLabel: 'Search providers',
  searchPlaceholder: 'Search providers...',
  capabilityLabel: 'Filter by capability',
  mediaLabel: 'Filter by media type',
  loadError: 'Could not load providers. Try again.',
  pinError: 'Could not update the pinned provider. Try again.',
  empty: 'No providers match these filters.',
  retry: 'Retry',
  loading: 'Loading providers…',
  pin: 'Pin',
  unpin: 'Unpin',
};

const DEFAULT_FILTERS = { q: '', capability: '', media: '' };
const FILTER_KEYS = ['q', 'capability', 'media'];

function sameFilters(left, right) {
  return FILTER_KEYS.every(key => (left[key] || '') === (right[key] || ''));
}

function sortPinned(items) {
  return items.sort((left, right) => Number(right.pinned) - Number(left.pinned));
}

function normalizeOptions(options) {
  return (options || []).map(option => typeof option === 'string'
    ? { value: option, label: option }
    : { ...option, value: option.value ?? option.label });
}

function resolveLabels(defaults, model, labels, t) {
  const translate = typeof t === 'function' ? t : text => model?.labels?.[text] ?? text;
  const translated = {};
  for (const [key, text] of Object.entries(defaults)) translated[key] = translate(text);
  return { ...translated, ...(model?.labels || {}), ...(labels || {}) };
}

/**
 * Universal provider directory. Filtering stays server-authoritative through
 * the adapter's onFetch, which receives the resolved filter object and an abort
 * signal. Navigation and pin writes are intents; this component never uses a
 * browser URL, DOM node or transport.
 *
 * onFetch({ filters, signal }) -> { items } or an item array
 * onFiltersChange(filters, key), onPin(item, { pinned }) -> { pinned }, onNavigate(url)
 * and optional onOpenProvider(item), onRetry() are supplied by the adapter.
 */
export function ProviderDirectoryView({
  model = {},
  t,
  labels,
  palette = {},
  buttonPalette = {},
  initialFilters,
  filters: controlledFilters,
  skipInitialLoad,
  debounceMs = 300,
  onFetch,
  onFiltersChange,
  subscribeHistory,
  onPin,
  onNavigate,
  onOpenProvider,
  onRetry,
}) {
  const colors = { ...DEFAULT_PALETTE, ...palette };
  const buttons = { ...DEFAULT_BUTTON_PALETTE, ...buttonPalette };
  const copy = resolveLabels(DEFAULT_LABELS, model, labels, t);
  const { width } = useWindowDimensions();
  const narrow = width < 768;
  const [localFilters, setLocalFilters] = useState(() => ({
    ...DEFAULT_FILTERS,
    ...(model.filters || {}),
    ...(initialFilters || {}),
  }));
  const initialFiltersRef = useRef(localFilters);
  const [items, setItems] = useState(() => Array.isArray(model.items) ? model.items : []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [pinPending, setPinPending] = useState('');
  const [pinError, setPinError] = useState(false);
  const pinOverrides = useRef(new Map());
  const initialLoad = useRef(true);
  const skipInitial = useRef(skipInitialLoad ?? Boolean((model.items || []).length));
  const onFetchRef = useRef(onFetch);
  onFetchRef.current = onFetch;
  const filters = controlledFilters ?? localFilters;
  const canPin = model.canPin !== false && typeof onPin === 'function';

  useEffect(() => {
    if (initialLoad.current) {
      initialLoad.current = false;
      if (skipInitial.current && sameFilters(filters, initialFiltersRef.current)) return undefined;
    }
    const loader = onFetchRef.current;
    if (typeof loader !== 'function') {
      setError(true);
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(false);
      try {
        const result = await loader({ filters: { ...filters }, signal: controller.signal });
        if (controller.signal.aborted) return;
        const nextItems = Array.isArray(result) ? result : result?.items;
        if (!Array.isArray(nextItems)) throw new Error('Directory response missing items');
        setItems(sortPinned(nextItems.map(item => ({ ...item,
          pinned: pinOverrides.current.has(item.slug) ? pinOverrides.current.get(item.slug) : item.pinned,
        }))));
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [filters.q, filters.capability, filters.media, retry, debounceMs]);

  useEffect(() => subscribeHistory?.(next => {
    const resolved = { ...DEFAULT_FILTERS, ...next };
    if (controlledFilters === undefined) setLocalFilters(resolved);
    onFiltersChange?.(resolved, 'history');
  }), [subscribeHistory]);

  function update(key, value) {
    const next = { ...filters, [key]: value };
    if (controlledFilters === undefined) setLocalFilters(next);
    onFiltersChange?.(next, key);
  }

  function retryLoad() {
    setError(false);
    setRetry(value => value + 1);
    onRetry?.();
  }

  async function togglePin(item) {
    if (pinPending) return;
    setPinPending(item.slug);
    setPinError(false);
    try {
      if (typeof onPin !== 'function') throw new Error('Pin adapter missing');
      const result = await onPin(item, { pinned: !item.pinned });
      const pinned = typeof result === 'boolean' ? result : Boolean(result?.pinned ?? !item.pinned);
      pinOverrides.current.set(item.slug, pinned);
      setItems(current => sortPinned(current.map(row => row.slug === item.slug ? { ...row, pinned } : row)));
    } catch {
      setPinError(true);
    } finally {
      setPinPending('');
    }
  }

  function openItem(item) {
    if (typeof onOpenProvider === 'function') {
      onOpenProvider(item);
      return;
    }
    if (item.url) onNavigate?.(item.url, item);
  }

  return <View testID="provider-directory" style={[styles.container, { backgroundColor: colors.surface, borderRadius: colors.radius }]}>
    <View style={styles.header}>
      <View style={styles.titleRow}>
        <View style={styles.titleGroup}>
          <View style={[styles.titleIcon, { fontSize: 24, color: colors.link || colors.accent }]}>
            {model.icon ? <Icon spec={model.icon} />
              : <Text accessible={false} style={[styles.titleGlyph, { color: colors.link || colors.accent }]}>⛁</Text>}
          </View>
          <Text role="heading" aria-level={2} style={[styles.title, { color: colors.text }]}>{copy.providers}</Text>
        </View>
        {model.setupUrl && typeof onNavigate === 'function' ? <Pressable accessibilityRole="link"
          onPress={() => onNavigate(model.setupUrl)}>
          <Text style={[styles.setupLink, { color: colors.link || colors.accent }]}>{copy.setup}</Text>
        </Pressable> : null}
      </View>
      <Text style={[styles.description, { color: colors.textMuted }]}>{copy.description}</Text>
    </View>

    <View style={[styles.toolbar, narrow && styles.toolbarNarrow]}>
      <View style={styles.searchField}>
        <View style={[styles.searchInput, {
          backgroundColor: colors.surfaceStrong, borderColor: colors.border,
          borderRadius: colors.radius,
        }]}>
          <View style={[styles.searchIcon, { fontSize: 20, color: colors.textMuted }]}>
            {model.searchIcon ? <Icon spec={model.searchIcon} />
              : <Text accessible={false} style={[styles.searchGlyph, { color: colors.textMuted }]}>⌕</Text>}
          </View>
          <TextInput id="provider-search" accessibilityLabel={copy.searchLabel}
            name="q" autoCapitalize="none" autoComplete="off" autoCorrect={false}
            placeholder={copy.searchPlaceholder} placeholderTextColor={colors.textMuted}
            value={filters.q || ''} onChangeText={value => update('q', value)}
            style={[styles.searchText, { color: colors.text }]} />
        </View>
      </View>
      <View style={[styles.filterGroup, narrow && styles.filterGroupNarrow]}>
      <View style={[styles.filterField, narrow && styles.filterFieldNarrow]}>
        <FilterDropdown label={copy.capabilityLabel} id="provider-capability" name="capability"
          options={normalizeOptions(model.capabilities)} value={filters.capability || ''}
          palette={colors}
          leadingIcon={model.filterIcon ? <View style={{ fontSize: 16, color: colors.textMuted }}><Icon spec={model.filterIcon} /></View> : undefined}
          onChange={event => update('capability', event.target.value)} />
      </View>
      <View style={[styles.filterField, narrow && styles.filterFieldNarrow]}>
        <FilterDropdown label={copy.mediaLabel} id="provider-media" name="media"
          options={normalizeOptions(model.media)} value={filters.media || ''}
          palette={colors}
          leadingIcon={model.filterIcon ? <View style={{ fontSize: 16, color: colors.textMuted }}><Icon spec={model.filterIcon} /></View> : undefined}
          onChange={event => update('media', event.target.value)} />
      </View>
      </View>
    </View>

    {error ? <View accessibilityRole="alert" style={[styles.alert, { borderColor: colors.danger }]}>
      <Text style={[styles.copyText, { color: colors.textSecondary }]}>{copy.loadError}</Text>
      <Button label={copy.retry} tone="surface" onPress={retryLoad} palette={buttons} />
    </View> : null}
    {pinError ? <Text accessibilityRole="alert" style={[styles.copyText, { color: colors.danger }]}>
      {copy.pinError}
    </Text> : null}
    {loading ? <Text accessibilityLiveRegion="polite" style={[styles.copyText, { color: colors.textMuted }]}>
      {copy.loading}
    </Text> : null}

    <View accessibilityState={{ busy: loading }}>
      <CatalogGrid>
        {items.map(item => <CatalogCard key={item.slug} title={item.title} description={item.description}
          href={item.url} logo={item.logo} label={item.openLabel} attention={item.attention} status={item.status}
          pinned={Boolean(item.pinned)}
          pinLabel={item.pinned ? (item.unpinLabel || copy.unpin) : (item.pinLabel || copy.pin)}
          pinDisabled={Boolean(pinPending)}
          onPin={canPin ? () => togglePin(item) : undefined}
          onPress={typeof onOpenProvider === 'function' || typeof onNavigate === 'function'
            ? () => openItem(item) : undefined}
          palette={colors} />)}
        {!items.length ? <Text accessibilityLiveRegion="polite"
          style={[styles.empty, { color: colors.textMuted }]}>{copy.empty}</Text> : null}
      </CatalogGrid>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  container: { gap: 24, padding: 24, minWidth: 0 },
  titleGroup: { flexDirection: 'row', alignItems: 'center', gap: 12, minWidth: 0, flexShrink: 1 },
  titleIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  titleGlyph: { fontSize: 24, lineHeight: 24 },
  setupLink: { fontSize: 12, lineHeight: 18, textDecorationLine: 'underline' },
  header: { gap: 16 },
  titleRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { flexShrink: 1, fontSize: 20, lineHeight: 30, fontWeight: '600' },
  description: { fontSize: 14, lineHeight: 21 },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  toolbarNarrow: { flexDirection: 'column', alignItems: 'stretch' },
  filterGroup: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  filterGroupNarrow: { gap: 8 },
  filterFieldNarrow: { flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 0 },
  searchField: { flexGrow: 1, flexShrink: 1, minWidth: 0 },
  searchInput: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, height: 38 },
  searchIcon: { position: 'absolute', left: 12, width: 20, height: 20, alignItems: 'center', justifyContent: 'center' },
  searchGlyph: { fontSize: 20, lineHeight: 20 },
  searchText: { flex: 1, minWidth: 0, paddingLeft: 40, paddingRight: 12, paddingVertical: 8, fontSize: 14, lineHeight: 20 },
  filterField: { flexGrow: 0, flexShrink: 0 },
  alert: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, padding: 12 },
  copyText: { fontSize: 12, lineHeight: 17 },
  empty: { fontSize: 12, lineHeight: 17 },
});
