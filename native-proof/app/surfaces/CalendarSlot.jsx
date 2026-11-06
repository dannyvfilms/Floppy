import React from 'react';
import { StyleSheet, View } from 'react-native';
import { ReleaseCalendar } from '../../../frontend/ui/ReleaseCalendar';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'RELEASE-CALENDAR',
  title: 'Release calendar',
  where: 'Calendar month, agenda, list and subscription links',
  status: 'ported',
  note: 'The shared calendar renders the server-owned month grid, agenda, list with media/status/release/tag filters, month/view toolbar and the calendar actions menu. The Calendar screen adds the shared calendar-links panel with release/history feeds, switchable filters, subscription URL and copy/download actions, and persists native filter and week-start choices through the shell adapter. Month and range loads use /api/v1/calendar/ through the session facade; the API exposes per-user tracking status only as part of media rows, not calendar events, so the status filter stays hidden instead of showing fixture statuses. The calendar token needed for the subscription links is not exposed by a read endpoint, so those links stay placeholder text. Web React ownership was browser-verified, while iOS and Android runtime were not exercised.',
};

const mediaTypes = [
  { value: 'tv', label: 'TV Shows', shortLabel: 'TV Show' },
  { value: 'season', label: 'TV Seasons', shortLabel: 'TV Season' },
  { value: 'movie', label: 'Movies', shortLabel: 'Movie' },
  { value: 'anime', label: 'Anime', shortLabel: 'Anime' },
  { value: 'book', label: 'Books', shortLabel: 'Book' },
  { value: 'game', label: 'Games', shortLabel: 'Game' },
  { value: 'podcast', label: 'Podcasts', shortLabel: 'Podcast' },
  { value: 'manga', label: 'Manga', shortLabel: 'Manga' },
  { value: 'comic', label: 'Comics', shortLabel: 'Comic' },
  { value: 'boardgame', label: 'Board Games', shortLabel: 'Board Game' },
  { value: 'music', label: 'Music', shortLabel: 'Music' },
  { value: 'video', label: 'Videos', shortLabel: 'Video' },
];

const releaseTypes = [
  { value: 'digital', label: 'Digital' },
  { value: 'physical', label: 'Physical' },
];

const statusesByType = {};

const defaultFilters = {
  selectedTypes: mediaTypes.map((item) => item.value),
  selectedStatusesByType: {},
  selectedReleaseTypes: releaseTypes.map((item) => item.value),
};

const calendarPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  surfaceHover: palette.surfaceStrong,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  link: '#818cf8',
  danger: palette.danger,
  overlay: 'rgba(24, 24, 27, 0.78)',
};

const menu = {
  labels: {
    menu: 'Calendar Actions',
    today: 'Go to Today',
    fetch: 'Fetch New Releases',
    download: 'Download Calendar',
    weekStart: 'Week starts on',
    monday: 'Monday',
    sunday: 'Sunday',
  },
};

const navigation = {
  previous: 'previous',
  next: 'next',
  today: 'today',
};

export default function CalendarSlot({
  model,
  onOpenRelease,
  onNavigate,
  onMenuAction,
  onFiltersChange,
  initialFilters,
  weekStart,
}) {
  if (!model) {
    return null;
  }
  return <View style={styles.wrapper}>
    <ReleaseCalendar
      month={model.month}
      year={model.year}
      monthName={model.monthName}
      weekdayHeaders={model.weekdayHeaders}
      weeks={model.weeks}
      daysInMonth={model.daysInMonth}
      dayLabels={model.dayLabels}
      today={model.today}
      selectedDay={model.selectedDay}
      view="grid"
      releases={model.releases}
      mediaTypes={mediaTypes}
      releaseTypes={releaseTypes}
      statusesByType={statusesByType}
      initialFilters={initialFilters || defaultFilters}
      navigation={navigation}
      menu={{ ...menu, weekStart: weekStart || 'monday' }}
      palette={calendarPalette}
      onNavigate={onNavigate}
      onOpenRelease={onOpenRelease}
      onFiltersChange={onFiltersChange}
      onMenuAction={onMenuAction} />
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { marginTop: spacing.xs },
});