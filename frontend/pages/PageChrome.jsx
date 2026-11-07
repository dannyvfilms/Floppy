import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { Spinner } from '../ui/Spinner';

// Shared page pieces for the web ↔ Expo page compositions. They own the page
// heading, section framing and the loading/error/empty states so both adapters
// use the same order, copy and controls.

export const pagePalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentText: '#ffffff',
  danger: '#ef4444',
};

function mergePalette(palette) {
  return { ...pagePalette, ...(palette || {}) };
}

export function PageHeading({
  title,
  subtitle,
  count,
  countLabel,
  actions,
  palette,
  titleLevel = 1,
}) {
  const colors = mergePalette(palette);
  const countText = count == null ? '' : `${count}${countLabel ? ` ${countLabel}` : ''}`;
  return <View style={styles.heading}>
    <View style={styles.headingText}>
      <View style={styles.titleRow}>
        <Text role="heading" aria-level={titleLevel} style={[styles.title, { color: colors.text }]}>
          {title}
        </Text>
        {countText ? <View style={[styles.count, { backgroundColor: colors.surface }]}>
          <Text style={[styles.countText, { color: colors.textSecondary }]}>{countText}</Text>
        </View> : null}
      </View>
      {subtitle ? <Text style={[styles.subtitle, { color: colors.textMuted }]}>{subtitle}</Text> : null}
    </View>
    {actions ? <View style={styles.headingActions}>{actions}</View> : null}
  </View>;
}

export function PageSection({ title, copy, actions, children, palette }) {
  if (!title && !copy && !children) return null;
  const colors = mergePalette(palette);
  return <View style={styles.section}>
    {title || actions ? <View style={styles.sectionHeading}>
      <View style={styles.headingText}>
        {title ? <Text role="heading" aria-level={2} style={[styles.sectionTitle, { color: colors.text }]}>
          {title}
        </Text> : null}
        {copy ? <Text style={[styles.sectionCopy, { color: colors.textMuted }]}>{copy}</Text> : null}
      </View>
      {actions ? <View style={styles.headingActions}>{actions}</View> : null}
    </View> : null}
    {children}
  </View>;
}

export function PageState({
  state = 'ready',
  labels = {},
  palette,
  empty,
  error,
  onRetry,
  onEmptyAction,
}) {
  const colors = mergePalette(palette);
  if (state === 'loading') {
    return <View accessibilityLiveRegion="polite" style={styles.loading}>
      <Spinner color={colors.accent} />
      <Text style={[styles.stateText, { color: colors.textMuted }]}>{labels.loading || 'Loading…'}</Text>
    </View>;
  }
  if (state === 'error') {
    const copy = error || {};
    return <View style={[styles.stateBox, { backgroundColor: colors.surface, borderColor: colors.danger }]}>
      <Text role="heading" aria-level={2} style={[styles.stateTitle, { color: colors.text }]}>
        {copy.title || labels.errorTitle || 'This page could not load'}
      </Text>
      <Text style={[styles.stateText, { color: colors.textMuted }]}>
        {copy.body || labels.errorBody || 'Please try again.'}
      </Text>
      {onRetry ? <Button label={copy.retryLabel || labels.retry || 'Try again'} tone="surface"
        palette={colors} onPress={onRetry} /> : null}
    </View>;
  }
  if (state === 'empty') {
    const copy = empty || {};
    return <View style={[styles.empty, { backgroundColor: colors.surface }]}>
      <Text role="heading" aria-level={2} style={[styles.emptyTitle, { color: colors.text }]}>
        {copy.title || labels.emptyTitle || 'Nothing here yet'}
      </Text>
      {copy.body ? <Text style={[styles.stateText, { color: colors.textMuted }]}>{copy.body}</Text> : null}
      {onEmptyAction && (copy.actionLabel || labels.emptyAction) ? <Pressable
        accessibilityRole="button"
        onPress={onEmptyAction}
        style={[styles.emptyAction, { backgroundColor: colors.accent }]}>
        <Text style={[styles.emptyActionText, { color: colors.accentText }]}>
          {copy.actionLabel || labels.emptyAction}
        </Text>
      </Pressable> : null}
    </View>;
  }
  return null;
}

const styles = StyleSheet.create({
  heading: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
  },
  headingText: { flexShrink: 1, minWidth: 0, gap: 4 },
  titleRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  subtitle: { fontSize: 14, lineHeight: 20 },
  count: { borderRadius: 6, paddingHorizontal: 14, paddingVertical: 7 },
  countText: { fontSize: 13, fontWeight: '600' },
  headingActions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  section: { gap: 12 },
  sectionHeading: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
  },
  sectionTitle: { fontSize: 17, lineHeight: 24, fontWeight: '600' },
  sectionCopy: { fontSize: 12, lineHeight: 17 },
  loading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  stateBox: { borderWidth: 1, borderRadius: 8, padding: 16, gap: 8, alignItems: 'flex-start' },
  stateTitle: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  stateText: { fontSize: 14, lineHeight: 20 },
  empty: { alignItems: 'center', justifyContent: 'center', borderRadius: 8, paddingVertical: 56, paddingHorizontal: 24, gap: 8 },
  emptyTitle: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
  emptyAction: { borderRadius: 6, paddingHorizontal: 16, paddingVertical: 9, marginTop: 8 },
  emptyActionText: { fontSize: 13, fontWeight: '600' },
});
