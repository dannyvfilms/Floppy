import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Spinner } from './Spinner';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  accent: '#6366f1',
  accentText: '#ffffff',
  danger: '#ef4444',
  radius: 8,
};

const defaultLabels = {
  placeholder: 'Search for a parent…',
  loading: 'Loading matches…',
  empty: 'No matches found.',
  errorTitle: 'Parent search could not load',
  errorBody: 'Please try again.',
  retry: 'Try again',
  selected: 'Selected',
};

export function ParentPicker({
  title,
  description,
  query = '',
  placeholder,
  results = [],
  selectedId = null,
  state = 'ready',
  labels = {},
  palette: paletteOverrides,
  onQueryChange,
  onSelect,
  onRetry,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, ...labels };
  return <View style={[styles.parent, { backgroundColor: palette.surface, borderColor: palette.border }]} testID={testID}>
    {title ? <Text role="heading" aria-level={3} style={[styles.parentTitle, { color: palette.text }]}>{title}</Text> : null}
    {description ? <Text style={[styles.description, { color: palette.textMuted }]}>{description}</Text> : null}
    {onQueryChange ? <TextInput
      accessibilityLabel={title || copy.placeholder}
      value={query}
      onChangeText={onQueryChange}
      placeholder={placeholder || copy.placeholder}
      placeholderTextColor={palette.textMuted}
      autoComplete="off"
      autoCorrect={false}
      autoCapitalize="none"
      returnKeyType="search"
      style={[styles.input, {
        color: palette.text,
        backgroundColor: palette.surfaceStrong,
        borderColor: palette.border,
        borderRadius: palette.radius,
      }]}
    /> : null}
    {state === 'loading' ? <View style={styles.stateRow}>
      <Spinner size={16} color={palette.accent} />
      <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.loading}</Text>
    </View> : null}
    {state === 'error' ? <View style={styles.error}>
      <Text role="heading" aria-level={4} style={[styles.errorTitle, { color: palette.text }]}>{copy.errorTitle}</Text>
      <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.errorBody}</Text>
      {onRetry ? <Pressable accessibilityRole="button" onPress={onRetry}
        style={[styles.retry, { backgroundColor: palette.accent, borderRadius: palette.radius }]}>
        <Text style={[styles.retryText, { color: palette.accentText }]}>{copy.retry}</Text>
      </Pressable> : null}
    </View> : null}
    {state === 'ready' ? (results.length ? results.map((row, index) => {
      const selected = selectedId != null && String(row.id) === String(selectedId);
      return <Pressable key={row.id ?? index}
        accessibilityRole="button"
        accessibilityLabel={[row.title, row.subtitle].filter(Boolean).join(', ')}
        accessibilityState={{ selected }}
        onPress={() => onSelect?.(row)}
        style={({ pressed }) => [styles.parentRow, {
          borderColor: palette.border,
          borderTopWidth: index === 0 ? 0 : 1,
          backgroundColor: pressed ? palette.surfaceStrong : 'transparent',
        }]}>
        <View style={styles.rowText}>
          <Text style={[styles.parentRowTitle, { color: palette.text }]}>{row.title}</Text>
          {row.subtitle ? <Text style={[styles.parentRowSubtitle, { color: palette.textMuted }]}>{row.subtitle}</Text> : null}
        </View>
        {selected ? <Text style={[styles.selected, { color: palette.accent }]}>{copy.selected}</Text> : null}
      </Pressable>;
    }) : <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.empty}</Text>) : null}
  </View>;
}

const styles = StyleSheet.create({
  parent: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 8 },
  parentTitle: { fontSize: 15, fontWeight: '600' },
  description: { fontSize: 12, lineHeight: 17 },
  input: { borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13 },
  parentRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 },
  rowText: { flex: 1, minWidth: 0, gap: 2 },
  parentRowTitle: { fontSize: 14, fontWeight: '600' },
  parentRowSubtitle: { fontSize: 12 },
  selected: { fontSize: 11, fontWeight: '700', letterSpacing: 0.4 },
  stateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 },
  stateText: { fontSize: 13, lineHeight: 18 },
  error: { gap: 6, paddingVertical: 4 },
  errorTitle: { fontSize: 14, fontWeight: '600' },
  retry: { alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 7, marginTop: 2 },
  retryText: { fontSize: 12, fontWeight: '600' },
});
