import React from 'react';
import { StyleSheet, View } from 'react-native';
import { ReleaseCalendar } from '../../../frontend/ui/ReleaseCalendar';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'RELEASE-CALENDAR',
  title: 'Release calendar',
  where: 'Calendar month, agenda, list and subscription links',
  status: 'in_progress',
  note: 'The shared calendar renders the server-owned month grid, agenda and list with media/status/release/tag filters, month/view toolbar and the calendar actions menu. The Calendar screen adds the shared calendar-links panel with release/history feeds, switchable filters, subscription URL and copy/download actions. Server queries, week start, calendar tokens and ICS delivery stay authoritative; durable native filter and week-start persistence is still being added, and runtime was not exercised.',
};

const WEEKDAYS = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
];

const dayLabels = Object.fromEntries(
  Array.from({ length: 30 }, (_, index) => {
    const day = index + 1;
    return [String(day), WEEKDAYS[index % WEEKDAYS.length]];
  }),
);

function artwork(seed, width, height) {
  return `https://picsum.photos/seed/${seed}/${width}/${height}`;
}

const releases = {
  '4': [
    {
      id: 'quiet-orbit-s2e5',
      mediaType: 'season',
      mediaLabel: 'TV Season',
      releaseType: '',
      releaseTypeLabel: '',
      status: 'In progress',
      title: 'The Quiet Orbit',
      href: '/demo/the-quiet-orbit',
      image: artwork('floppy-orbit', 400, 600),
      poster: artwork('floppy-orbit', 400, 600),
      episodeLabel: 'S02E05',
      eventTime: 'at 9:00 PM',
      subtitle: 'S02E05 at 9:00 PM',
      unknownTime: false,
      sortTime: 1762300000,
      cardLines: ['2024', '6 / 10 episodes'],
    },
    {
      id: 'dune-digital',
      mediaType: 'movie',
      mediaLabel: 'Movie',
      releaseType: 'digital',
      releaseTypeLabel: 'Digital',
      status: 'Planning',
      title: 'Dune: Part Three',
      href: '/demo/dune-part-three',
      image: artwork('floppy-dune', 400, 600),
      poster: artwork('floppy-dune', 400, 600),
      episodeLabel: '',
      eventTime: 'at 12:00 AM',
      subtitle: 'Digital release at 12:00 AM',
      unknownTime: false,
      sortTime: 1762260000,
      cardLines: ['2026'],
    },
  ],
  '6': [
    {
      id: 'signal-static',
      mediaType: 'podcast',
      mediaLabel: 'Podcast',
      releaseType: '',
      releaseTypeLabel: '',
      status: 'In progress',
      title: 'Signal & Static',
      href: '/demo/signal-and-static',
      image: artwork('floppy-signal', 400, 400),
      poster: artwork('floppy-signal', 400, 400),
      episodeLabel: '',
      eventTime: 'at 6:00 AM',
      subtitle: 'at 6:00 AM',
      unknownTime: false,
      sortTime: 1762450000,
      cardLines: ['2023', '3 / 8 episodes'],
    },
  ],
  '10': [
    {
      id: 'river-of-stars',
      mediaType: 'book',
      mediaLabel: 'Book',
      releaseType: '',
      releaseTypeLabel: '',
      status: 'Planning',
      title: 'A River of Stars',
      href: '/demo/a-river-of-stars',
      image: artwork('floppy-river', 400, 600),
      poster: artwork('floppy-river', 400, 600),
      episodeLabel: '',
      eventTime: '',
      subtitle: 'Time unknown',
      unknownTime: true,
      sortTime: 0,
      cardLines: ['2026', 'Book 2 of 3'],
    },
  ],
  '14': [
    {
      id: 'hollow-crown-physical',
      mediaType: 'movie',
      mediaLabel: 'Movie',
      releaseType: 'physical',
      releaseTypeLabel: 'Physical',
      status: 'Completed',
      title: 'Hollow Crown',
      href: '/demo/hollow-crown',
      image: artwork('floppy-crown', 400, 600),
      poster: artwork('floppy-crown', 400, 600),
      episodeLabel: '',
      eventTime: 'at 12:00 AM',
      subtitle: 'Physical release at 12:00 AM',
      unknownTime: false,
      sortTime: 1763130000,
      cardLines: ['2025'],
    },
  ],
  '18': [
    {
      id: 'orbit-at-dawn',
      mediaType: 'season',
      mediaLabel: 'TV Season',
      releaseType: '',
      releaseTypeLabel: '',
      status: 'In progress',
      title: 'Orbit at Dawn',
      href: '/demo/orbit-at-dawn',
      image: artwork('floppy-dawn', 400, 600),
      poster: artwork('floppy-dawn', 400, 600),
      episodeLabel: 'S01E12',
      eventTime: 'at 11:30 AM',
      subtitle: 'S01E12 at 11:30 AM',
      unknownTime: false,
      sortTime: 1763470000,
      cardLines: ['2026', '11 / 12 episodes'],
    },
  ],
  '25': [
    {
      id: 'last-cartographer',
      mediaType: 'game',
      mediaLabel: 'Game',
      releaseType: '',
      releaseTypeLabel: '',
      status: 'Planning',
      title: 'The Last Cartographer',
      href: '/demo/the-last-cartographer',
      image: artwork('floppy-cartographer', 400, 600),
      poster: artwork('floppy-cartographer', 400, 600),
      episodeLabel: '',
      eventTime: '',
      subtitle: 'Time unknown',
      unknownTime: true,
      sortTime: 0,
      cardLines: ['2026'],
    },
  ],
};

const mediaTypes = [
  { value: 'tv', label: 'TV Shows', shortLabel: 'TV Show' },
  { value: 'season', label: 'TV Seasons', shortLabel: 'TV Season' },
  { value: 'movie', label: 'Movies', shortLabel: 'Movie' },
  { value: 'anime', label: 'Anime', shortLabel: 'Anime' },
  { value: 'book', label: 'Books', shortLabel: 'Book' },
  { value: 'game', label: 'Games', shortLabel: 'Game' },
  { value: 'podcast', label: 'Podcasts', shortLabel: 'Podcast' },
];

const releaseTypes = [
  { value: 'digital', label: 'Digital' },
  { value: 'physical', label: 'Physical' },
];

const statusesByType = {
  movie: [
    { value: 'Planning', label: 'Planning', inMonth: true },
    { value: 'In progress', label: 'In Progress', inMonth: false },
    { value: 'Completed', label: 'Completed', inMonth: true },
  ],
  season: [
    { value: 'In progress', label: 'In Progress', inMonth: true },
    { value: 'Completed', label: 'Completed', inMonth: false },
  ],
  anime: [
    { value: 'In progress', label: 'In Progress', inMonth: false },
  ],
  book: [
    { value: 'Planning', label: 'Planning', inMonth: true },
  ],
  game: [
    { value: 'Planning', label: 'Planning', inMonth: true },
  ],
  podcast: [
    { value: 'In progress', label: 'In Progress', inMonth: true },
  ],
};

const defaultFilters = {
  selectedTypes: mediaTypes.map((item) => item.value),
  selectedStatusesByType: Object.fromEntries(
    Object.entries(statusesByType).map(([type, statuses]) => [
      type,
      statuses.map((status) => status.value),
    ]),
  ),
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
  weekStart: 'monday',
  labels: {
    menu: 'Calendar Actions',
    today: 'Go to Today',
    fetch: 'Fetch New Releases',
    download: 'Download Calendar',
    weekStart: 'Week starts on',
    monday: 'Monday',
    sunday: 'Sunday',
  },
  urls: {
    today: '/demo/calendar',
    fetch: '/demo/calendar/fetch',
    download: '/demo/calendar.ics',
    preferences: '/demo/preferences',
  },
};

const navigation = {
  previous: '/demo/calendar?month=10&year=2026',
  next: '/demo/calendar?month=12&year=2026',
  today: '/demo/calendar?month=11&year=2026',
  views: {
    grid: '/demo/calendar?view=grid&month=11&year=2026',
    list: '/demo/calendar?view=list&month=11&year=2026',
  },
};

export default function CalendarSlot({ onOpenRelease, onMenuAction, onFiltersChange, initialFilters, weekStart }) {
  return <View style={styles.wrapper}>
    <ReleaseCalendar
      month={11}
      year={2026}
      monthName="November"
      weekdayHeaders={['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']}
      weeks={[
        [0, 0, 0, 0, 0, 0, 1],
        [2, 3, 4, 5, 6, 7, 8],
        [9, 10, 11, 12, 13, 14, 15],
        [16, 17, 18, 19, 20, 21, 22],
        [23, 24, 25, 26, 27, 28, 29],
        [30, 0, 0, 0, 0, 0, 0],
      ]}
      daysInMonth={Array.from({ length: 30 }, (_, index) => index + 1)}
      dayLabels={dayLabels}
      today={{ day: 4, month: 11, year: 2026 }}
      selectedDay={4}
      view="grid"
      releases={releases}
      mediaTypes={mediaTypes}
      releaseTypes={releaseTypes}
      statusesByType={statusesByType}
      initialFilters={initialFilters || defaultFilters}
      navigation={navigation}
      menu={{ ...menu, weekStart: weekStart || menu.weekStart }}
      palette={calendarPalette}
      onOpenRelease={onOpenRelease}
      onFiltersChange={onFiltersChange}
      onMenuAction={onMenuAction} />
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { marginTop: spacing.xs },
});
