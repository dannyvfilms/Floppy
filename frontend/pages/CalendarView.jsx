import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

// One Calendar composition for web and Expo. It owns the page heading, the
// empty note, the month section, the calendar-links heading/copy order and the
// action notice. The month grid (`calendar`) and the links panel (`links`) are
// content slots backed by the universal ReleaseCalendar and CalendarLinks; the
// platform adapter supplies server props, demo/server data and clipboard or
// navigation capabilities.

export const calendarLabels = {
  title: 'Calendar',
  subtitle: 'Upcoming releases and what lands next',
  empty: 'Nothing this month. Add a show, movie, book or game to your library and its upcoming dates appear here.',
  linksTitle: 'Calendar links',
  linksCopy: 'Add this link to any calendar app to see upcoming releases there.',
  loading: 'Loading calendar…',
  retry: 'Try again',
};

export function CalendarView({
  calendar = null,
  links = null,
  empty = false,
  notice = '',
  title,
  subtitle,
  labels = {},
  palette = {},
  chrome = true,
  loading = false,
  onRetry,
  sections = ['calendar', 'links'],
  header,
  footer,
  children,
}) {
  const copy = { ...calendarLabels, ...(labels || {}) };
  const heading = title === undefined ? copy.title : title;
  const subheading = subtitle === undefined ? copy.subtitle : subtitle;
  const show = key => sections.includes(key);
  return <View style={styles.root}>
    {header || null}
    {chrome && heading ? <Text accessibilityRole="header" style={[styles.title, { color: palette.text || '#fafafa' }]}>{heading}</Text> : null}
    {chrome && subheading ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{subheading}</Text> : null}
    {show('calendar') && empty && copy.empty
      ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{copy.empty}</Text>
      : null}
    {show('calendar')
      ? (loading
        ? <Text accessibilityLiveRegion="polite" style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
        : calendar)
      : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.notice, { color: palette.textMuted || '#a1a1aa' }]}>{notice}</Text> : null}
    {notice && onRetry ? <Pressable accessibilityRole="button" accessibilityLabel={copy.retry}
      onPress={onRetry} style={styles.retry}>
      <Text style={[styles.retryText, { color: palette.link || '#818cf8' }]}>{copy.retry}</Text>
    </Pressable> : null}
    {show('links') && links ? <View style={styles.section}>
      {copy.linksTitle ? <Text accessibilityRole="header" style={[styles.sectionTitle, { color: palette.text || '#fafafa' }]}>{copy.linksTitle}</Text> : null}
      {copy.linksCopy ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{copy.linksCopy}</Text> : null}
      {links}
    </View> : null}
    {footer || null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  subtitle: { fontSize: 13, lineHeight: 19 },
  section: { gap: 8 },
  sectionTitle: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  notice: { fontSize: 12, lineHeight: 17 },
  retry: { alignSelf: 'flex-start', paddingVertical: 4 },
  retryText: { fontSize: 13, fontWeight: '600' },
});
