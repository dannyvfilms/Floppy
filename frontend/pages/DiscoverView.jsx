import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { DiscoverScreen } from '../discover/DiscoverScreen';

// One Discover composition for web and Expo. It owns the page heading, the
// toolbar/tabs/feedback order, the rows and hidden sections, and the
// loading/empty states. The browser page mounts the shared Discover sections
// inside its Alpine-owned chrome; the native screen renders this view whole.

export const discoverLabels = {
  title: 'Discover',
  subtitle: '[UNDER CONSTRUCTION] Recommendations powered by global trends and your local activity.',
  retry: 'Try again',
  error: 'Discover could not be loaded.',
};

export function DiscoverView({
  title,
  subtitle,
  notice = '',
  error = '',
  labels = {},
  palette = {},
  chrome = true,
  header,
  footer,
  onRetry,
  children,
  ...discoverProps
}) {
  const copy = { ...discoverLabels, ...(labels || {}) };
  const heading = title === undefined ? copy.title : title;
  const subheading = subtitle === undefined ? copy.subtitle : subtitle;
  const message = error || notice;
  return <View style={styles.root}>
    {header || null}
    {chrome && heading ? <Text accessibilityRole="header" style={[styles.title, { color: palette.text || '#fafafa' }]}>{heading}</Text> : null}
    {chrome && subheading ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{subheading}</Text> : null}
    {message ? <View style={[styles.notice, { borderColor: palette.danger || '#ef4444' }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger || '#ef4444' }]}>{message}</Text>
      {onRetry ? <Text accessibilityRole="button" accessibilityLabel={copy.retry}
        onPress={onRetry} style={[styles.retry, { color: palette.link || '#818cf8' }]}>{copy.retry}</Text> : null}
    </View> : null}
    <DiscoverScreen {...discoverProps} labels={labels} palette={palette} />
    {footer || null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  subtitle: { fontSize: 13, lineHeight: 19 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  retry: { fontSize: 13, fontWeight: '600' },
});
