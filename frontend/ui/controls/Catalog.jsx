import React, { useLayoutEffect, useRef, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

const DEFAULT_PALETTE = {
  card: '#27272a',
  cardHovered: '#3f3f46',
  cardPressed: '#3f3f46',
  radius: 8,
  border: '#3f3f46',
  text: '#fafafa',
  textMuted: '#a1a1aa',
  focus: '#818cf8',
  statusNeutral: '#a1a1aa',
  statusSuccess: '#10b981',
  statusWarning: '#f59e0b',
  attention: '#fbbf24',
  pin: '#a1a1aa',
  pinActive: '#818cf8',
};

const STATUS_GLYPHS = { success: '✓', warning: '!', neutral: '–' };
const GRID_GAP = 12;
const AUTO_MIN_WIDTH = 240;
const COLUMN_BREAKPOINTS = [384, 608, 896];

function resolvePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function columnCount(width, auto) {
  if (width <= 0) return 1;
  if (auto) return Math.max(1, Math.floor((width + GRID_GAP) / (AUTO_MIN_WIDTH + GRID_GAP)));
  return COLUMN_BREAKPOINTS.reduce((columns, breakpoint) => columns + (width >= breakpoint ? 1 : 0), 1);
}

function statusColor(tone, palette) {
  if (tone === 'success') return palette.statusSuccess;
  if (tone === 'warning') return palette.statusWarning;
  return palette.statusNeutral;
}

function StatusMark({ status, attention, palette }) {
  if (status) {
    const info = typeof status === 'string' ? { label: status } : status;
    const tone = info.tone || 'neutral';
    return <Text accessibilityRole="image" accessibilityLabel={info.label || undefined}
      style={[styles.status, { color: statusColor(tone, palette) }]}>
      {STATUS_GLYPHS[tone] || STATUS_GLYPHS.neutral}
    </Text>;
  }
  if (!attention) return null;
  return <Text accessibilityRole="image" accessibilityLabel={attention}
    style={[styles.status, { color: palette.attention }]}>⚠</Text>;
}

/**
 * Responsive catalog grid. `auto` sizes columns from a 240pt minimum card width;
 * otherwise the legacy 1/2/3/4-column breakpoints apply. `className` and other
 * browser props are accepted only for call-site compatibility and are ignored.
 */
export function CatalogGrid({ children, auto = false, alignStart = false, testID = 'card-grid', ...legacyProps }) {
  const [width, setWidth] = useState(0);
  const frameRef = useRef(null);
  // Measure before paint so the first rendered frame already uses the final
  // column count. `onLayout`/ResizeObserver later keep it correct on resize.
  useLayoutEffect(() => {
    const node = frameRef.current;
    const measured = node?.offsetWidth || node?.getBoundingClientRect?.().width || 0;
    if (measured > 0) setWidth(current => Math.abs(current - measured) > 0.5 ? measured : current);
  }, []);
  const columns = columnCount(width, auto);
  const itemWidth = width > 0 ? (width - GRID_GAP * (columns - 1)) / columns : null;
  // `legacyProps` carries web-only props such as className; native presentation has no class names.
  void legacyProps;

  return <View style={styles.gridFrame} testID={testID}>
    <View
      ref={frameRef}
      onLayout={event => {
        const next = event?.nativeEvent?.layout?.width || 0;
        if (Math.abs(next - width) > 0.5) setWidth(next);
      }}
      style={[styles.grid, alignStart && styles.gridStart]}
    >
      {React.Children.toArray(children).map((child, index) => (
        <View key={child?.key ?? index} style={itemWidth ? { width: itemWidth } : styles.itemFull}>
          {child}
        </View>
      ))}
    </View>
  </View>;
}

/**
 * Catalog entry with an optional logo, status or attention marker, and a pin
 * action. Navigation is provided by `onPress`; `href` remains part of the model
 * so a platform adapter can attach its own link behavior.
 */
export function CatalogCard({
  title,
  description,
  logo,
  href,
  label,
  attention,
  status,
  pinned = false,
  pinLabel,
  onPin,
  pinDisabled = false,
  onPress,
  palette,
  style,
  testID,
}) {
  const colors = resolvePalette(palette);
  const hasPin = typeof onPin === 'function';

  return <View style={[styles.item, style]} testID={testID}>
    <Pressable
      accessibilityRole={href ? 'link' : 'button'}
      accessibilityLabel={label || title}
      onPress={onPress}
      style={({ pressed, hovered, focused }) => [
        styles.card,
        {
          paddingRight: hasPin ? 44 : 16,
          borderRadius: colors.radius,
          backgroundColor: focused ? colors.border : (pressed ? colors.border : hovered ? colors.border : colors.surfaceStrong),
        },
      ]}
    >
      <View style={styles.heading}>
        <View style={styles.headingMain}>
          {logo ? <Image source={{ uri: logo }} style={styles.logo}
            accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" /> : null}
          <Text numberOfLines={2} style={[styles.title, { color: colors.text }]}>{title}</Text>
        </View>
        <StatusMark status={status} attention={attention} palette={colors} />
      </View>
      {description ? <Text numberOfLines={2}
        style={[styles.description, { color: colors.textMuted }]}>{description}</Text> : null}
    </Pressable>
    {hasPin ? <Pressable
      accessibilityRole="button"
      accessibilityLabel={pinLabel || (pinned ? 'Unpin' : 'Pin')}
      accessibilityState={{ disabled: pinDisabled, selected: Boolean(pinned) }}
      aria-pressed={Boolean(pinned)}
      disabled={pinDisabled}
      onPress={event => {
        event?.stopPropagation?.();
        if (!pinDisabled) onPin();
      }}
      style={({ pressed, hovered, focused }) => [
        styles.pin,
        { opacity: pinDisabled ? 0.6 : pressed ? 0.7 : 1 },
        focused && { borderColor: colors.focus },
        hovered && !pinDisabled && { backgroundColor: colors.cardHovered },
      ]}
    >
      <Text style={[styles.pinGlyph, { color: pinned ? colors.pinActive : colors.pin }]}>
        {pinned ? '★' : '☆'}
      </Text>
    </Pressable> : null}
  </View>;
}

const styles = StyleSheet.create({
  gridFrame: { width: '100%', minWidth: 0 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'stretch', gap: GRID_GAP },
  gridStart: { alignItems: 'flex-start' },
  itemFull: { width: '100%' },
  item: { minWidth: 0, position: 'relative' },
  card: {
    flexGrow: 1,
    gap: 8,
    minWidth: 0,
    padding: 16,
  },
  heading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 },
  headingMain: { flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 },
  logo: { width: 24, height: 24, resizeMode: 'contain', flexShrink: 0 },
  title: { flexShrink: 1, fontSize: 16, lineHeight: 24, fontWeight: '500' },
  description: { fontSize: 12, lineHeight: 16 },
  status: { flexShrink: 0, fontSize: 16, lineHeight: 20, fontWeight: '700' },
  pin: {
    position: 'absolute',
    right: 12,
    top: 14,
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'transparent',
    borderRadius: 4,
  },
  pinGlyph: { fontSize: 16, lineHeight: 20 },
});
