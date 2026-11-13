import React from 'react';
import { StyleSheet, View } from 'react-native';
import { ReleaseCalendar } from '../../../frontend/ui/ReleaseCalendar';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'RELEASE-CALENDAR',
  title: 'Release calendar',
  where: 'Calendar month, agenda, list and subscription links',
  status: 'ported',
  note: 'The shared calendar renders the server-owned month grid, agenda, month toolbar, the filter menu and the calendar actions menu. Media types, statuses, release types and the account week start come from GET /api/v1/calendar/links/; events come from /api/v1/calendar/ with the viewer status merged in from /api/v1/calendar/statuses/, so the status filter is real. TV episode releases map to the season type the web filters use. The region-unset notice shows when the account has no watch-provider region. Web React ownership was browser-verified earlier; iOS and Android runtime were not exercised.',
};

const calendarPalette = () => ({
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  surfaceMutedSoft: palette.surfaceMutedSoft,
  surfaceHover: palette.surfaceStrong,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: palette.accentContrast,
  link: palette.link,
  danger: palette.danger,
  overlay: palette.overlay,
});

const regionNotice = 'Set your watch provider region in Preferences to see digital and physical dates.';

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
  options,
  regionUnset = false,
  onOpenPreferences,
  onOpenRelease,
  onNavigate,
  onMenuAction,
  onFiltersChange,
  initialFilters,
  weekStart,
}) {
  if (!model || !options) {
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
      mediaTypes={options.mediaTypes}
      releaseTypes={options.releaseTypes}
      statusesByType={options.statusesByType}
      initialFilters={initialFilters || options.initialFilters}
      regionUnset={regionUnset}
      regionNotice={regionNotice}
      onOpenPreferences={onOpenPreferences}
      navigation={navigation}
      menu={{ ...menu, weekStart: weekStart || 'monday' }}
      palette={calendarPalette()}
      onNavigate={onNavigate}
      onOpenRelease={onOpenRelease}
      onFiltersChange={onFiltersChange}
      onMenuAction={onMenuAction} />
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { marginTop: spacing.xs },
});
