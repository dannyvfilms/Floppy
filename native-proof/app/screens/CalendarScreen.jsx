import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text } from 'react-native';
import { CalendarLinks } from '../../../frontend/ui/CalendarLinks';
import { Screen, Section } from '../components/Screen';
import { readCalendarPreferences, writeCalendarPreferences } from '../data/calendarPreferences';
import { createCalendarTransport } from '../data/calendarTransport';
import CalendarSlot from '../surfaces/CalendarSlot';
import DateTimeSlot from '../surfaces/DateTimeSlot';
import { palette, spacing } from '../theme';

const defaultWeekStart = 'monday';

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
  const preferences = useRef({ filters: null, weekStart: defaultWeekStart });
  const [filters, setFilters] = useState(null);
  const [weekStart, setWeekStart] = useState(defaultWeekStart);
  const [hydrated, setHydrated] = useState(false);
  const [actionNote, setActionNote] = useState('');

  useEffect(() => {
    let active = true;
    readCalendarPreferences().then((stored) => {
      if (!active) {
        return;
      }
      const next = {
        filters: stored?.filters || null,
        weekStart: stored?.weekStart === 'sunday' ? 'sunday' : defaultWeekStart,
      };
      preferences.current = next;
      setFilters(next.filters);
      setWeekStart(next.weekStart);
      setHydrated(true);
    });
    return () => {
      active = false;
    };
  }, []);

  function savePreferences(patch) {
    const next = { ...preferences.current, ...patch };
    preferences.current = next;
    writeCalendarPreferences(next);
  }

  function handleFiltersChange(next) {
    setFilters(next);
    savePreferences({ filters: next });
  }

  function handleMenuAction({ key, value }) {
    if (key === 'weekStart') {
      setWeekStart(value);
      savePreferences({ weekStart: value });
      setActionNote(`Week starts on ${value === 'sunday' ? 'Sunday' : 'Monday'}.`);
      return;
    }
    if (key === 'fetch') {
      const transport = createCalendarTransport();
      if (transport.mode !== 'server') {
        setActionNote('Sign in to your Floppy server to fetch new releases.');
        return;
      }
      setActionNote('Fetching new releases…');
      transport.fetchReleases()
        .then(() => setActionNote('Release fetch queued on the Django server.'))
        .catch(error => setActionNote(error.message || 'Could not fetch new releases.'));
      return;
    }
    if (key === 'download') {
      setActionNote('Calendar downloads use the subscription link below.');
    }
  }

  return <Screen title="Calendar" subtitle="Upcoming releases and what lands next">
    <Section title="This month">
      {hydrated ? <CalendarSlot
        initialFilters={filters || undefined}
        weekStart={weekStart}
        onFiltersChange={handleFiltersChange}
        onMenuAction={handleMenuAction}
        onOpenRelease={() => navigate('Detail')} /> : null}
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
