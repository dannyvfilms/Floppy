import React, { useState } from 'react';
import { StyleSheet, Text } from 'react-native';
import { CalendarLinks } from '../../../frontend/ui/CalendarLinks';
import { Screen, Section } from '../components/Screen';
import CalendarSlot from '../surfaces/CalendarSlot';
import DateTimeSlot from '../surfaces/DateTimeSlot';
import { palette, spacing } from '../theme';

let savedFilters = null;
let savedWeekStart = 'monday';

const releaseMediaTypes = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'season', label: 'TV Seasons' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'book', label: 'Books' },
  { value: 'game', label: 'Games' },
  { value: 'podcast', label: 'Podcasts' },
];

const historyMediaTypes = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'manga', label: 'Manga' },
  { value: 'game', label: 'Games' },
  { value: 'book', label: 'Books' },
  { value: 'comic', label: 'Comics' },
  { value: 'boardgame', label: 'Board Games' },
  { value: 'music', label: 'Music' },
  { value: 'podcast', label: 'Podcasts' },
  { value: 'video', label: 'Videos' },
];

const historyDefaultTypes = historyMediaTypes
  .filter((item) => !['music', 'podcast', 'video'].includes(item.value))
  .map((item) => item.value);

const statuses = [
  { value: 'Planning', label: 'Planning' },
  { value: 'In progress', label: 'In Progress' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Dropped', label: 'Dropped' },
];

const releaseTypes = [
  { value: 'digital', label: 'Digital' },
  { value: 'physical', label: 'Physical' },
];

const calendarLinkPalette = {
  ...palette,
  surfaceDim: palette.surfaceStrong,
  accentText: '#ffffff',
  link: '#818cf8',
};

export default function CalendarScreen({ navigate }) {
  const [weekStart, setWeekStart] = useState(savedWeekStart);
  const [actionNote, setActionNote] = useState('');

  function handleFiltersChange(next) {
    savedFilters = next;
  }

  function handleMenuAction({ key, value }) {
    if (key === 'weekStart') {
      savedWeekStart = value;
      setWeekStart(value);
      setActionNote(`Week starts on ${value === 'sunday' ? 'Sunday' : 'Monday'}.`);
      return;
    }
    if (key === 'fetch') {
      setActionNote('Fetch requested. Release fetching runs on the Django server.');
      return;
    }
    if (key === 'download') {
      setActionNote('Calendar downloads use the subscription link below.');
    }
  }

  return <Screen title="Calendar" subtitle="Upcoming releases and what lands next">
    <Section title="This month">
      <CalendarSlot
        initialFilters={savedFilters || undefined}
        weekStart={weekStart}
        onFiltersChange={handleFiltersChange}
        onMenuAction={handleMenuAction}
        onOpenRelease={() => navigate('Detail')} />
      {actionNote ? <Text style={styles.note}>{actionNote}</Text> : null}
    </Section>
    <Section title="Calendar links">
      <CalendarLinks
        releaseMediaTypes={releaseMediaTypes}
        historyMediaTypes={historyMediaTypes}
        statuses={statuses}
        releaseTypes={releaseTypes}
        initialHistoryMediaTypes={historyDefaultTypes}
        releaseBaseUrl="https://app.floppy.example/calendar/demo-token.ics"
        historyBaseUrl="https://app.floppy.example/calendar/history/demo-token.ics"
        palette={calendarLinkPalette} />
    </Section>
    <Section title="Tracking dates">
      <DateTimeSlot />
    </Section>
  </Screen>;
}

const styles = StyleSheet.create({
  note: { color: palette.textMuted, fontSize: 12, paddingHorizontal: spacing.xs },
});
