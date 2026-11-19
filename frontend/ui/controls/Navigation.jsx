import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

// Universal replacements for the frozen web helpers in `controls.jsx`:
// `ScrollRow`, `Tabs` and `FilterToolbar`. They keep the legacy call shapes
// (`selectedKey`, `items`, `selected`, `label`, `onSelect`) but render only
// React Native primitives, so the same code can back web, iOS and Android.
// Browser-only concerns (navigation URLs, htmx, forms, className) stay in the
// platform adapter that supplies `onSelect` and the surrounding page.

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceHover: '#3f3f46',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentText: '#ffffff',
  focus: '#6366f1',
};

const defaultGap = 8;
const defaultHintWidth = 28;
const fadeSteps = [0.92, 0.7, 0.42, 0.16];

function resolvePalette(palette) {
  return { ...defaultPalette, ...(palette || {}) };
}

function itemKey(item, index) {
  if (item == null) return index;
  if (item.key != null) return item.key;
  if (item.value != null) return item.value;
  if (item.url != null) return item.url;
  return index;
}

function childKey(child, index) {
  return child && child.key != null ? String(child.key) : String(index);
}

// Legacy web callers may still hand over presentational props. Drop the ones
// React Native cannot use instead of leaking them onto a primitive.
function nativeProps(props) {
  const safe = { ...props };
  delete safe.className;
  delete safe.dataSet;
  delete safe.dangerouslySetInnerHTML;
  return safe;
}

function EdgeFade({ side, color, width }) {
  const steps = side === 'start' ? fadeSteps : [...fadeSteps].reverse();
  return <View pointerEvents="none" accessible={false}
    style={[styles.edgeFade, side === 'start' ? styles.edgeFadeStart : styles.edgeFadeEnd, { width }]}>
    {steps.map((opacity, index) => <View key={index} accessible={false}
      style={[styles.fadeStep, { backgroundColor: color, opacity }]} />)}
  </View>;
}

// Horizontal row that never wraps: a soft overlay on the side with more to
// scroll to, and the selected child centered in view when its key is known.
// Pass `selectedKey` (child key) or `selectedIndex`. The overlay is built from
// stacked translucent views, so it needs no gradient dependency or DOM.
export function ScrollRow({
  as,
  children,
  selectedKey,
  selectedIndex,
  horizontal = true,
  centerSelected = true,
  edgeHints = false,
  hintColor,
  hintWidth = defaultHintWidth,
  gap = defaultGap,
  scrollRef,
  style,
  contentContainerStyle,
  accessibilityLabel,
  label,
  palette,
  onScroll,
  onLayout,
  onContentSizeChange,
  ...rest
}) {
  const colors = resolvePalette(palette);
  const localRef = useRef(null);
  const layoutRef = useRef({});
  const metricsRef = useRef({ x: 0, width: 0, content: 0 });
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [metrics, setMetrics] = useState(metricsRef.current);

  const setScrollRef = useCallback(node => {
    localRef.current = node;
    if (typeof scrollRef === 'function') scrollRef(node);
    else if (scrollRef && typeof scrollRef === 'object') scrollRef.current = node;
  }, [scrollRef]);

  const recordLayout = useCallback((key, index, event) => {
    const { x, width } = event.nativeEvent.layout;
    const previous = layoutRef.current[key];
    layoutRef.current[key] = { x, width };
    layoutRef.current[`index:${index}`] = { x, width };
    if (!previous || Math.abs(previous.x - x) > 0.5 || Math.abs(previous.width - width) > 0.5) {
      setLayoutVersion(current => current + 1);
    }
  }, []);

  const updateMetrics = useCallback(next => {
    metricsRef.current = next;
    setMetrics(current => (
      current.x === next.x && current.width === next.width && current.content === next.content
        ? current
        : next
    ));
  }, []);

  function handleScroll(event) {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    updateMetrics({
      x: contentOffset.x,
      width: layoutMeasurement.width,
      content: contentSize.width,
    });
    onScroll?.(event);
  }

  function handleLayout(event) {
    updateMetrics({ ...metricsRef.current, width: event.nativeEvent.layout.width });
    onLayout?.(event);
  }

  function handleContentSizeChange(width, height) {
    updateMetrics({ ...metricsRef.current, content: width });
    onContentSizeChange?.(width, height);
  }

  useEffect(() => {
    if (!horizontal || !centerSelected) return;
    const targetKey = selectedIndex != null
      ? `index:${selectedIndex}`
      : selectedKey != null
        ? `key:${String(selectedKey)}`
        : null;
    if (!targetKey) return;
    const target = layoutRef.current[targetKey];
    if (!target || metrics.width <= 0) return;
    const max = Math.max(0, metrics.content - metrics.width);
    const desired = Math.max(0, Math.min(max, target.x + target.width / 2 - metrics.width / 2));
    if (Math.abs(desired - metrics.x) < 1) return;
    const node = localRef.current;
    if (node?.scrollTo) node.scrollTo({ x: desired, y: 0, animated: true });
    else if (node?.scrollToOffset) node.scrollToOffset({ offset: desired, animated: true });
  }, [centerSelected, horizontal, layoutVersion, metrics.content, metrics.width, metrics.x, selectedIndex, selectedKey]);

  const atStart = metrics.x > 1;
  const atEnd = metrics.content > metrics.width + 1 && metrics.x + metrics.width < metrics.content - 1;
  const showHints = horizontal && edgeHints && (atStart || atEnd);
  const hint = hintColor || colors.background;
  const role = rest.role || rest.accessibilityRole
    || (as === 'nav' ? 'navigation' : as === 'group' ? 'group' : undefined);
  const resolvedLabel = accessibilityLabel || label;
  const safeRest = nativeProps(rest);
  delete safeRest.role;
  delete safeRest.accessibilityRole;

  const content = horizontal
    ? React.Children.map(children, (child, index) => {
      const key = childKey(child, index);
      return <View key={`${key}::${index}`} style={styles.horizontalItem}
        onLayout={event => {
          recordLayout(`key:${key}`, index, event);
        }}>
        {child}
      </View>;
    })
    : children;

  return <View style={[styles.wrapper, style]}>
    <ScrollView ref={setScrollRef} horizontal={horizontal} nestedScrollEnabled
      showsHorizontalScrollIndicator={false} showsVerticalScrollIndicator={false}
      scrollEventThrottle={16} onScroll={handleScroll} onLayout={handleLayout}
      onContentSizeChange={handleContentSizeChange}
      accessibilityLabel={resolvedLabel} role={role}
      style={horizontal ? styles.scroll : styles.scrollVertical}
      contentContainerStyle={[
        horizontal ? styles.horizontalContent : styles.verticalContent,
        { gap },
        contentContainerStyle,
      ]}
      {...safeRest}>
      {content}
    </ScrollView>
    {showHints && atStart ? <EdgeFade side="start" color={hint} width={hintWidth} /> : null}
    {showHints && atEnd ? <EdgeFade side="end" color={hint} width={hintWidth} /> : null}
  </View>;
}

// Tab strip with real tab semantics: one `tab` per item, selected state on the
// active item and a labeled `tablist` container. `onSelect(key, item)` is the
// adapter-owned switch; when it is absent the item is disabled rather than
// pretending a press did something. Items may use `key` or `value`, and an
// `onPress` fallback is honored for one-off surfaces.
export function Tabs({
  items = [],
  selected,
  label,
  onSelect,
  edgeHints = true,
  hintColor,
  palette,
  style,
  itemStyle,
  accessibilityLabel,
  scrollRef,
  ...rest
}) {
  const colors = resolvePalette(palette);
  const tabs = items.map((item, index) => {
    const key = itemKey(item, index);
    const isSelected = selected != null && String(selected) === String(key);
    const press = onSelect ? () => onSelect(key, item) : item?.onPress;
    const disabled = Boolean(item?.disabled) || !press;
    return { item, index, key, isSelected, press, disabled };
  });

  return <ScrollRow {...rest} scrollRef={scrollRef} selectedKey={selected == null ? undefined : String(selected)}
    edgeHints={edgeHints} hintColor={hintColor || colors.surface} palette={colors} gap={20}
    accessibilityLabel={accessibilityLabel || label} role={rest.role || rest.accessibilityRole || 'tablist'}
    style={[styles.tabs, { borderBottomColor: colors.border }, style]}>
    {tabs.map(({ item, index, key, isSelected, press, disabled }) => <Pressable
      key={String(key) + ':' + index}
      accessibilityRole="tab"
      aria-selected={isSelected}
      accessibilityLabel={item?.label == null ? String(key) : String(item.label)}
      accessibilityState={{ selected: isSelected, disabled }}
      disabled={disabled}
      onPress={press}
      style={({ pressed, focused }) => [
        styles.tab,
        itemStyle,
        { borderBottomColor: isSelected ? colors.accent : 'transparent' },
        pressed && styles.pressed,
        focused && !isSelected && { borderBottomColor: colors.focus },
        disabled && styles.disabled,
      ]}>
      <Text numberOfLines={1} style={[styles.tabLabel, {
        color: isSelected ? colors.accent : colors.textMuted,
      }]}>{item?.label == null ? String(key) : item.label}</Text>
    </Pressable>)}
  </ScrollRow>;
}

// Search/filter toolbar shell: a wrapping row that keeps field labels and
// accessible names from the supplied children. The browser adapter owns any
// form submission; this component only lays the controls out.
export function FilterToolbar({
  children,
  label,
  accessibilityLabel,
  style,
  as,
  ...rest
}) {
  const safeRest = nativeProps(rest);
  delete safeRest.role;
  delete safeRest.accessibilityRole;
  delete safeRest.palette;
  delete safeRest.onSubmit;
  delete safeRest.action;
  delete safeRest.method;
  return <View accessibilityLabel={accessibilityLabel || label}
    role={rest.role || rest.accessibilityRole || (as === 'form' ? 'form' : 'toolbar')}
    style={[styles.toolbar, style]} {...safeRest}>
    {children}
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { position: 'relative', maxWidth: '100%' },
  scroll: { flexGrow: 0 },
  scrollVertical: { flexGrow: 0 },
  horizontalContent: { flexDirection: 'row', flexWrap: 'nowrap', alignItems: 'center' },
  verticalContent: { flexDirection: 'column', alignItems: 'stretch' },
  horizontalItem: { flexShrink: 0 },
  edgeFade: { position: 'absolute', top: 0, bottom: 0, flexDirection: 'row' },
  edgeFadeStart: { left: 0 },
  edgeFadeEnd: { right: 0 },
  fadeStep: { flex: 1 },
  tabs: { borderBottomWidth: 1 },
  tab: { paddingVertical: 12, borderBottomWidth: 2, justifyContent: 'center' },
  tabLabel: { fontSize: 14, fontWeight: '500', lineHeight: 20 },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.5 },
  toolbar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'flex-start',
    columnGap: 16,
    rowGap: 16,
    minWidth: 0,
  },
});
