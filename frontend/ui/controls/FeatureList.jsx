import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

/**
 * Universal feature rows and media-type marks.
 *
 * `FeatureList` keeps the legacy `{ items }` contract. Each item may be a
 * string or an object with `key`, `label`, `description` (or the older
 * `note`), `tone`, `status` and contribution data. The contribution may be a
 * string shown as detail or an object supplying the same fields as fallbacks.
 * Presentation is native-owned; callers supply data, labels and an optional
 * palette.
 */

const FALLBACK_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  info: '#818cf8',
  neutral: '#a1a1aa',
};

const STATUS_GLYPHS = {
  success: '✓',
  warning: '!',
  danger: '×',
  info: 'i',
  neutral: '–',
};

const TONE_LABELS = {
  success: 'Active',
  warning: 'Needs attention',
  danger: 'Error',
  info: 'Information',
  neutral: 'Inactive',
};

const MEDIA_GLYPHS = {
  tv: '▭',
  movie: '▷',
  anime: '◎',
  book: '▤',
  manga: '▥',
  comic: '▦',
  game: '◉',
  boardgame: '▦',
  music: '♪',
  podcast: '◉',
  video: '▶',
};

const MEDIA_LABELS = {
  tv: 'TV',
  movie: 'Movie',
  anime: 'Anime',
  book: 'Book',
  manga: 'Manga',
  comic: 'Comic',
  game: 'Game',
  boardgame: 'Board game',
  music: 'Music',
  podcast: 'Podcast',
  video: 'Video',
};

function resolvePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function normalizeTone(tone) {
  if (tone === 'error' || tone === 'failure') return 'danger';
  return STATUS_GLYPHS[tone] ? tone : 'neutral';
}

function toneColor(tone, palette) {
  return palette[normalizeTone(tone)] || palette.neutral;
}

function contributionFields(contribution) {
  if (!contribution) return {};
  if (typeof contribution === 'string') return { description: contribution };
  return typeof contribution === 'object' ? contribution : {};
}

function normalizeItem(item, index) {
  if (item === null || item === undefined) return { key: index, label: '' };
  if (typeof item === 'string' || typeof item === 'number') {
    return { key: index, label: String(item) };
  }

  const contribution = contributionFields(item.contribution);
  const status = item.status ?? contribution.status;
  const statusInfo = status && typeof status === 'object' ? status : null;
  return {
    ...contribution,
    ...item,
    key: item.key ?? item.id ?? index,
    label: item.label ?? item.title ?? contribution.label ?? '',
    description: item.description ?? item.note ?? item.detail
      ?? contribution.description ?? contribution.note ?? contribution.detail ?? '',
    status: statusInfo ? statusInfo.label ?? '' : status ?? '',
    tone: item.tone ?? contribution.tone ?? statusInfo?.tone,
  };
}

function StatusMark({ label, tone, palette }) {
  const resolvedTone = normalizeTone(tone);
  return <Text
    accessible
    accessibilityRole="image"
    accessibilityLabel={label}
    testID="status-icon"
    style={[styles.statusMark, { color: toneColor(resolvedTone, palette) }]}>
    {STATUS_GLYPHS[resolvedTone]}
  </Text>;
}

export function FeatureList({
  items = [],
  palette: paletteOverrides,
  onSelect,
  emptyLabel,
  style,
  testID = 'feature-list',
}) {
  const palette = resolvePalette(paletteOverrides);
  const rows = (items || []).map(normalizeItem);

  if (!rows.length) {
    return emptyLabel
      ? <Text style={[styles.empty, { color: palette.textMuted }, style]} testID={testID}>{emptyLabel}</Text>
      : null;
  }

  return <View accessibilityRole="list" style={[styles.list, style]} testID={testID}>
    {rows.map((item, index) => {
      const status = item.status;
      const tone = normalizeTone(item.tone ?? (status ? 'success' : 'neutral'));
      const statusLabel = status
        ? `${item.label}: ${status}`
        : tone === 'neutral' ? item.label : `${item.label}: ${TONE_LABELS[tone]}`;
      const interactive = typeof item.onPress === 'function' || typeof onSelect === 'function';
      const body = <>
        <StatusMark label={statusLabel} tone={tone} palette={palette} />
        <View style={styles.body} testID="feature-copy">
          <Text style={[styles.label, { color: palette.text }]}>{item.label}</Text>
          {item.description ? <Text style={[styles.description, { color: palette.textMuted }]}>
            {item.description}
          </Text> : null}
          {status && tone !== 'success' ? <Text testID="feature-state" style={[styles.state, { color: toneColor(tone, palette) }]}>
            {status}
          </Text> : null}
        </View>
      </>;

      if (!interactive) {
        return <View key={item.key ?? index} accessibilityRole="listitem" testID="feature-row" style={styles.row}>
          {body}
        </View>;
      }

      return <Pressable
        key={item.key ?? index}
        accessibilityRole="button"
        accessibilityLabel={[item.label, item.description, status].filter(Boolean).join(', ')}
        accessibilityState={{ disabled: Boolean(item.disabled), selected: Boolean(item.selected) }}
        disabled={Boolean(item.disabled)}
        onPress={() => (item.onPress ?? onSelect)?.(item)}
        style={({ pressed, focused }) => [
          styles.row,
          styles.interactiveRow,
          pressed && { backgroundColor: palette.rowPressed || palette.surfaceHover || 'rgba(127, 127, 127, 0.16)' },
          focused && palette.focusStyle,
          item.disabled && styles.disabled,
        ]}>
        {body}
      </Pressable>;
    })}
  </View>;
}

export function MediaIcon({
  type,
  size = 20,
  color,
  glyph,
  label,
  renderIcon,
  palette: paletteOverrides,
  style,
  testID = 'feature-list',
}) {
  const palette = resolvePalette(paletteOverrides);
  const resolvedType = String(type || '');
  const accessibleLabel = label || MEDIA_LABELS[resolvedType] || resolvedType || 'Media';
  const iconColor = color || palette.textMuted;
  const dimensions = { width: size, height: size, minWidth: size };
  const render = typeof renderIcon === 'function' ? renderIcon({
    type: resolvedType,
    size,
    color: iconColor,
    label: accessibleLabel,
  }) : null;

  if (render !== null && render !== undefined) {
    return <View accessible accessibilityRole="image" accessibilityLabel={accessibleLabel}
      style={[styles.mediaIcon, dimensions, style]} testID={testID}>
      {render}
    </View>;
  }

  return <Text
    accessible
    accessibilityRole="image"
    accessibilityLabel={accessibleLabel}
    style={[styles.mediaGlyph, dimensions, { color: iconColor, fontSize: Math.max(12, size * 0.9) }, style]}
    testID={testID}>
    {glyph || MEDIA_GLYPHS[resolvedType] || (resolvedType ? resolvedType.slice(0, 2).toUpperCase() : '●')}
  </Text>;
}

const styles = StyleSheet.create({
  list: { width: '100%', minWidth: 0 },
  row: { flexDirection: 'row', alignItems: 'flex-start', columnGap: 8, paddingVertical: 6 },
  interactiveRow: { borderRadius: 6, paddingHorizontal: 4 },
  body: { flexShrink: 1, minWidth: 0, rowGap: 2 },
  label: { fontSize: 14, lineHeight: 19, fontWeight: '500' },
  description: { fontSize: 12, lineHeight: 17 },
  state: { fontSize: 12, lineHeight: 17, fontWeight: '600' },
  statusMark: { flexShrink: 0, width: 18, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  empty: { fontSize: 13, lineHeight: 18 },
  disabled: { opacity: 0.5 },
  mediaIcon: { alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  mediaGlyph: { textAlign: 'center', includeFontPadding: false },
});
