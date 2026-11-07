import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';

const DEFAULT_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  text: '#fafafa',
  textMuted: '#a1a1aa',
  warning: '#f59e0b',
  danger: '#ef4444',
  success: '#10b981',
  radius: 8,
  radiusSmall: 6,
};

const DEFAULT_LABELS = {
  loading: 'Refreshing in the background...',
  stale: 'Showing saved data while it refreshes.',
  error: 'Refresh failed. Showing saved data.',
  complete: 'Refresh complete.',
  dismiss: 'Dismiss refresh notice',
  retry: 'Try again',
  offline: 'Waiting for a connection.',
  retrying: 'Retrying shortly.',
};

const TONES = {
  loading: 'warning',
  stale: 'warning',
  error: 'danger',
  complete: 'success',
};

function buttonPalette(colors) {
  return {
    radius: colors.radiusSmall,
    surface: {
      background: colors.surfaceStrong,
      pressed: colors.surface,
      hovered: colors.surface,
      text: colors.text,
      border: colors.border,
    },
    focusStyle: {},
  };
}

/** Shared cache/refresh notice for loading, stale, error and completed
 * refreshes. The browser pollers and lifecycle stay in the existing adapters;
 * this component renders the state they report on web and native.
 */
export function RefreshNotice({
  state = 'loading',
  message,
  labels = {},
  palette = {},
  background,
  border,
  color,
  onDismiss,
  onRetry,
  attempt,
  retryAfter = 0,
  offline = false,
  children,
}) {
  if (!state || state === 'idle') return null;
  const colors = { ...DEFAULT_PALETTE, ...palette };
  const copy = { ...DEFAULT_LABELS, ...labels };
  const tone = TONES[state] || 'warning';
  const textColor = color || colors[tone] || colors.text;
  const toneBackground = background
    || (state === 'loading' || state === 'stale' ? colors.surfaceStrong : colors.surface);
  const toneBorder = border || colors[tone] || colors.border;
  const note = offline
    ? copy.offline
    : retryAfter > 0
      ? `${copy.retrying} ${retryAfter}s`
      : attempt > 0 ? `${copy.retrying} (${attempt})` : null;

  return <View accessibilityLiveRegion="polite"
    accessibilityRole={state === 'error' ? 'alert' : undefined}
    style={[styles.notice, { backgroundColor: toneBackground, borderColor: toneBorder }]}>
    <View style={styles.body}>
      <Text style={[styles.message, { color: textColor }]}>{message || copy[state] || copy.loading}</Text>
      {note ? <Text style={[styles.note, { color: colors.textMuted }]}>{note}</Text> : null}
    </View>
    {onRetry ? <Button label={copy.retry} size="sm" tone="surface"
      palette={buttonPalette(colors)} onPress={onRetry} /> : null}
    {onDismiss ? <Pressable accessibilityRole="button" accessibilityLabel={copy.dismiss}
      onPress={onDismiss} style={styles.dismiss}>
      <Text style={[styles.dismissText, { color: textColor }]}>✕</Text>
    </Pressable> : null}
    {children}
  </View>;
}

const styles = StyleSheet.create({
  notice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  body: { flex: 1, gap: 2 },
  message: { fontSize: 13, lineHeight: 18, fontWeight: '500' },
  note: { fontSize: 11, lineHeight: 15 },
  dismiss: { padding: 4 },
  dismissText: { fontSize: 13, fontWeight: '600' },
});
