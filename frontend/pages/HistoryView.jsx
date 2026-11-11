import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { HistoryFeed } from '../ui/HistoryFeed';

// One History composition for web and Expo. It owns the heading, the
// transport/notice order and the feed section; HistoryFeed owns the month
// navigation, filters, day groups, pagination and loading/empty/error states.
// The browser page passes chrome={false} because the Django template keeps its
// own page heading and month chrome as the server fallback.

export const historyLabels = {
  title: 'History',
  subtitle: 'Everything you have watched, read and played',
  retry: 'Try again',
  error: 'History could not be loaded.',
};

export function HistoryView({
  model = {},
  title,
  subtitle,
  labels = {},
  palette = {},
  chrome = true,
  error = '',
  notice = '',
  header,
  footer,
  children,
  Feed = HistoryFeed,
  onRetry,
  ...feedProps
}) {
  const copy = { ...historyLabels, ...(labels || {}) };
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
    <Feed model={model} labels={labels} palette={palette} chrome={chrome}
      onRetry={onRetry} {...feedProps} />
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
