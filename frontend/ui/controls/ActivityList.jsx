import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Spinner } from '../Spinner';

/** Bounded, keyboard-focusable activity list. Mirrors the legacy provider
 * activity rows (title/meta, summary, status) while accepting either explicit
 * children or plain item descriptors. Loading, error and empty states are
 * announced; callers own the data, labels and palette.
 */

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceHover: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  danger: '#ef4444',
  warning: '#f59e0b',
  success: '#10b981',
  radiusSmall: 6,
};

const defaultLabels = {
  loading: 'Loading activity…',
  empty: 'No activity yet.',
};

function toneColor(tone, palette) {
  if (tone === 'danger' || tone === 'failure') return palette.danger;
  if (tone === 'warning') return palette.warning;
  if (tone === 'success') return palette.success;
  return palette.textMuted;
}

function normalizeItem(item, index) {
  if (item === null || item === undefined) return { id: index, title: '' };
  if (typeof item === 'string' || typeof item === 'number') return { id: index, title: String(item) };
  return {
    ...item,
    id: item.id === undefined ? index : item.id,
    title: item.title ?? item.label ?? '',
  };
}

export function ActivityList({
  children,
  items,
  emptyLabel,
  palette: paletteOverrides,
  onOpenDetails,
  loading = false,
  error = null,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, empty: emptyLabel || defaultLabels.empty };
  const rows = (items || []).map(normalizeItem);
  const hasRows = rows.length > 0 || (children !== undefined && children !== null);
  return <ScrollView
    accessibilityRole="list"
    focusable
    nestedScrollEnabled
    style={[styles.scroll, { borderColor: palette.border, maxHeight: 320 }]}
    contentContainerStyle={styles.content}>
    {loading ? <View style={styles.stateRow}>
      <Spinner size={16} color={palette.accent} />
      <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.loading}</Text>
    </View> : error ? <View accessibilityRole="alert" style={styles.state}>
      <Text style={[styles.stateText, { color: palette.danger }]}>
        {typeof error === 'string' ? error : 'Could not load activity.'}
      </Text>
      {typeof error === 'string' ? null : error}
    </View> : !hasRows ? <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.empty}</Text> : <>
      {children}
      {rows.map((row, index) => {
        const detail = row.detail ?? row.summary ?? null;
        const interactive = typeof onOpenDetails === 'function';
        const body = <>
          <View style={styles.heading}>
            <Text style={[styles.title, { color: palette.text }]}>{row.title}</Text>
            {row.meta ? <Text style={[styles.meta, { color: palette.textSecondary }]}>{row.meta}</Text> : null}
          </View>
          {detail ? <Text style={[styles.meta, { color: palette.textMuted }]}>{detail}</Text> : null}
          {row.status ? <Text style={[styles.status, { color: toneColor(row.tone, palette) }]}>{row.status}</Text> : null}
        </>;
        const frame = [styles.row, {
          borderColor: palette.border,
          borderTopWidth: index === 0 && !children ? 0 : 1,
          borderRadius: palette.radiusSmall,
        }];
        if (!interactive) return <View key={row.id} style={frame}>{body}</View>;
        return <Pressable key={row.id}
          accessibilityRole="button"
          accessibilityLabel={[row.title, row.meta, row.status].filter(Boolean).join(', ')}
          onPress={() => onOpenDetails(row)}
          style={({ pressed }) => [...frame, pressed && { backgroundColor: palette.surfaceHover }]}>
          {body}
        </Pressable>;
      })}
    </>}
  </ScrollView>;
}

const styles = StyleSheet.create({
  scroll: { borderWidth: 1, maxWidth: '100%' },
  content: { paddingHorizontal: 12, paddingVertical: 4 },
  row: { rowGap: 4, paddingVertical: 10, paddingHorizontal: 4 },
  heading: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', columnGap: 8 },
  title: { fontSize: 14, fontWeight: '600', flexShrink: 1 },
  meta: { fontSize: 12, lineHeight: 17, flexShrink: 0 },
  status: { fontSize: 11, fontWeight: '700', letterSpacing: 0.4 },
  stateRow: { flexDirection: 'row', alignItems: 'center', columnGap: 8, paddingVertical: 12 },
  state: { paddingVertical: 8, rowGap: 4 },
  stateText: { fontSize: 13, lineHeight: 18 },
});
