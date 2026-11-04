import React, { useMemo, useState } from 'react';
import { StatisticsSummary } from '../../../frontend/ui/StatisticsSummary';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import { statisticsPalette } from '../theme';

export const surface = {
  id: 'STATISTICS',
  status: 'ported',
  title: 'Statistics summary and activity overview',
  where: 'Statistics screen summary cards, highlights and range/media-type controls',
  note: 'The summary hero, highlight cards, five summary cards, activity comparison and range/media-type controls use the shared React Native presentation. Chart canvases and the comparison/taste views stay legacy until a native chart renderer is chosen.',
};

const charts = {
  id: 'STATISTICS-CHARTS',
  status: 'in_progress',
  title: 'Charts, comparison and taste views',
  where: 'Activity rhythm, activity history, hours, status/rating/completion charts and featured repeats',
  note: 'Chart canvases keep the web Chart.js renderer while the native chart renderer is being ported to React Native primitives.',
};

const ranges = [
  { value: 'Today', label: 'Today', dateLabel: 'Nov 4, 2026' },
  { value: 'Yesterday', label: 'Yesterday', dateLabel: 'Nov 3, 2026' },
  { value: 'This Week', label: 'This week', dateLabel: 'Nov 2 – Nov 4, 2026' },
  { value: 'Last 7 Days', label: 'Last 7 days', dateLabel: 'Oct 29 – Nov 4, 2026' },
  { value: 'This Month', label: 'Month to date', dateLabel: 'Nov 1 – Nov 4, 2026' },
  { value: 'Last 30 Days', label: 'Last 30 days', dateLabel: 'Oct 6 – Nov 4, 2026' },
  { value: 'Last 90 Days', label: 'Last 90 days', dateLabel: 'Aug 7 – Nov 4, 2026' },
  { value: 'This Year', label: 'Year to date', dateLabel: 'Jan 1 – Nov 4, 2026' },
  { value: 'Last 6 Months', label: 'Last 6 months', dateLabel: 'May 5 – Nov 4, 2026' },
  { value: 'Last 12 Months', label: 'Last 12 months', dateLabel: 'Nov 5, 2025 – Nov 4, 2026' },
  { value: 'All Time', label: 'All time', dateLabel: 'Every tracked day' },
];

const mediaTypes = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'game', label: 'Games' },
  { value: 'music', label: 'Music' },
  { value: 'podcast', label: 'Podcasts' },
  { value: 'book', label: 'Books' },
  { value: 'comic', label: 'Comics' },
];

const summaries = {
  all: {
    total: 348,
    completed: 296,
    totalHours: 742,
    totalDays: 30,
    averageScore: 8.2,
    hasScore: true,
    mostActiveDay: 'Saturday',
    mostActiveDayLabel: 'Saturday',
    mostActiveDayPercentage: 21,
    currentStreak: 6,
    longestStreak: 24,
    longestStreakStart: '2026-09-12',
    longestStreakDates: 'Sep 12 – Oct 5, 2026',
    typeLabel: 'titles',
    typeFlavor: 'stories, ideas, and worlds',
    comparison: {
      badge: '+18%',
      label: '+18%',
      state: 'up',
      periodLabel: 'last year',
      details: '742 hours this range · 628 hours in the previous range',
    },
  },
  tv: {
    total: 96,
    completed: 84,
    totalHours: 318,
    totalDays: 13,
    averageScore: 8.6,
    hasScore: true,
    mostActiveDay: 'Sunday',
    mostActiveDayLabel: 'Sunday',
    mostActiveDayPercentage: 24,
    currentStreak: 4,
    longestStreak: 19,
    longestStreakStart: '2026-08-24',
    longestStreakDates: 'Aug 24 – Sep 11, 2026',
    typeLabel: 'shows',
    typeFlavor: 'episodes and seasons',
    comparison: {
      badge: '+11%',
      label: '+11%',
      state: 'up',
      periodLabel: 'last year',
      details: '318 hours this range · 286 hours in the previous range',
    },
  },
  movie: {
    total: 74,
    completed: 68,
    totalHours: 162,
    totalDays: 6,
    averageScore: 8.1,
    hasScore: true,
    mostActiveDay: 'Saturday',
    mostActiveDayLabel: 'Saturday',
    mostActiveDayPercentage: 26,
    currentStreak: 2,
    longestStreak: 11,
    longestStreakStart: '2026-07-18',
    longestStreakDates: 'Jul 18 – Jul 28, 2026',
    typeLabel: 'films',
    typeFlavor: 'film and storytelling',
    comparison: {
      badge: '+7%',
      label: '+7%',
      state: 'up',
      periodLabel: 'last year',
      details: '162 hours this range · 151 hours in the previous range',
    },
  },
  anime: {
    total: 38,
    completed: 34,
    totalHours: 96,
    totalDays: 4,
    averageScore: 8.7,
    hasScore: true,
    mostActiveDay: 'Friday',
    mostActiveDayLabel: 'Friday',
    mostActiveDayPercentage: 28,
    currentStreak: 3,
    longestStreak: 9,
    longestStreakStart: '2026-06-05',
    longestStreakDates: 'Jun 5 – Jun 13, 2026',
    typeLabel: 'titles',
    typeFlavor: 'anime and storytelling',
    comparison: {
      badge: '+22%',
      label: '+22%',
      state: 'up',
      periodLabel: 'last year',
      details: '96 hours this range · 79 hours in the previous range',
    },
  },
  game: {
    total: 21,
    completed: 12,
    totalHours: 104,
    totalDays: 4,
    averageScore: 8.4,
    hasScore: true,
    mostActiveDay: 'Wednesday',
    mostActiveDayLabel: 'Wednesday',
    mostActiveDayPercentage: 32,
    currentStreak: 1,
    longestStreak: 6,
    longestStreakStart: '2026-10-14',
    longestStreakDates: 'Oct 14 – Oct 19, 2026',
    typeLabel: 'games',
    typeFlavor: 'play and adventure',
    comparison: {
      badge: '-4%',
      label: '-4%',
      state: 'down',
      periodLabel: 'last year',
      details: '104 hours this range · 108 hours in the previous range',
    },
  },
  music: {
    total: 62,
    completed: 58,
    totalHours: 34,
    totalDays: 1,
    averageScore: 7.9,
    hasScore: true,
    mostActiveDay: 'Thursday',
    mostActiveDayLabel: 'Thursday',
    mostActiveDayPercentage: 19,
    currentStreak: 2,
    longestStreak: 14,
    longestStreakStart: '2026-02-02',
    longestStreakDates: 'Feb 2 – Feb 15, 2026',
    typeLabel: 'albums',
    typeFlavor: 'music and discovery',
    comparison: {
      badge: '+3%',
      label: '+3%',
      state: 'up',
      periodLabel: 'last year',
      details: '34 hours this range · 33 hours in the previous range',
    },
  },
  podcast: {
    total: 19,
    completed: 16,
    totalHours: 42,
    totalDays: 2,
    averageScore: 8.0,
    hasScore: true,
    mostActiveDay: 'Monday',
    mostActiveDayLabel: 'Monday',
    mostActiveDayPercentage: 23,
    currentStreak: 5,
    longestStreak: 12,
    longestStreakStart: '2026-04-06',
    longestStreakDates: 'Apr 6 – Apr 17, 2026',
    typeLabel: 'podcasts',
    typeFlavor: 'listening and learning',
    comparison: {
      badge: '+9%',
      label: '+9%',
      state: 'up',
      periodLabel: 'last year',
      details: '42 hours this range · 39 hours in the previous range',
    },
  },
  book: {
    total: 28,
    completed: 18,
    totalHours: 58,
    totalDays: 2,
    averageScore: 8.3,
    hasScore: true,
    mostActiveDay: 'Tuesday',
    mostActiveDayLabel: 'Tuesday',
    mostActiveDayPercentage: 25,
    currentStreak: 3,
    longestStreak: 8,
    longestStreakStart: '2026-09-01',
    longestStreakDates: 'Sep 1 – Sep 8, 2026',
    typeLabel: 'books',
    typeFlavor: 'reading and discovery',
    comparison: {
      badge: '+5%',
      label: '+5%',
      state: 'up',
      periodLabel: 'last year',
      details: '58 hours this range · 55 hours in the previous range',
    },
  },
  comic: {
    total: 10,
    completed: 6,
    totalHours: 12,
    totalDays: 0,
    averageScore: 8.5,
    hasScore: true,
    mostActiveDay: 'Friday',
    mostActiveDayLabel: 'Friday',
    mostActiveDayPercentage: 30,
    currentStreak: 1,
    longestStreak: 4,
    longestStreakStart: '2026-03-13',
    longestStreakDates: 'Mar 13 – Mar 16, 2026',
    typeLabel: 'comics',
    typeFlavor: 'comics and art',
    comparison: {
      badge: '0%',
      label: '0%',
      state: 'neutral',
      periodLabel: 'last year',
      details: '12 hours this range · 12 hours in the previous range',
    },
  },
};

const highlights = {
  all: [
    {
      key: 'first-play',
      label: 'First Play',
      title: 'Dune: Part Two',
      meta: '2h 46min · Movie',
      date: 'Played Nov 8, 2025',
      image: 'https://picsum.photos/seed/floppy-dune/600/400',
      href: '/demo/dune-part-two',
    },
    {
      key: 'last-play',
      label: 'Last Play',
      title: 'The Quiet Orbit',
      meta: 'S02E04 · 48min',
      date: 'Played yesterday',
      image: 'https://picsum.photos/seed/floppy-orbit/600/400',
      href: '/demo/the-quiet-orbit',
    },
    {
      key: 'today',
      label: 'Today',
      title: 'The Lantern Keeper',
      meta: 'Chapter 18 · 32min',
      date: 'Read today',
      image: 'https://picsum.photos/seed/floppy-lantern/600/400',
      href: '/demo/the-lantern-keeper',
    },
  ],
  tv: [
    {
      key: 'first-play',
      label: 'First Play',
      title: 'The Quiet Orbit',
      meta: 'S01E01 · 51min',
      date: 'Played Nov 12, 2025',
      image: 'https://picsum.photos/seed/floppy-orbit/600/400',
      href: '/demo/the-quiet-orbit',
    },
    {
      key: 'last-play',
      label: 'Last Play',
      title: 'The Quiet Orbit',
      meta: 'S02E04 · 48min',
      date: 'Played yesterday',
      image: 'https://picsum.photos/seed/floppy-orbit/600/400',
      href: '/demo/the-quiet-orbit',
    },
    {
      key: 'today',
      label: 'Today',
      title: 'The Quiet Orbit',
      meta: 'S02E05 · 52min',
      date: 'Airs tonight',
      image: 'https://picsum.photos/seed/floppy-orbit/600/400',
      href: '/demo/the-quiet-orbit',
    },
  ],
  movie: [
    {
      key: 'first-play',
      label: 'First Play',
      title: 'Dune: Part Two',
      meta: '2h 46min',
      date: 'Played Nov 8, 2025',
      image: 'https://picsum.photos/seed/floppy-dune/600/400',
      href: '/demo/dune-part-two',
    },
    {
      key: 'last-play',
      label: 'Last Play',
      title: 'Arrival',
      meta: '1h 56min',
      date: 'Played Oct 26, 2026',
      image: 'https://picsum.photos/seed/floppy-arrival/600/400',
      href: '/demo/arrival',
    },
    {
      key: 'today',
      label: 'Today',
      title: 'The Batman',
      meta: '2h 56min',
      date: 'Watched today',
      image: 'https://picsum.photos/seed/floppy-batman/600/400',
      href: '/demo/the-batman',
    },
  ],
  book: [
    {
      key: 'first-play',
      label: 'First Play',
      title: 'The Lantern Keeper',
      meta: 'Chapter 1',
      date: 'Read Feb 2, 2026',
      image: 'https://picsum.photos/seed/floppy-lantern/600/400',
      href: '/demo/the-lantern-keeper',
    },
    {
      key: 'last-play',
      label: 'Last Play',
      title: 'The Lantern Keeper',
      meta: 'Chapter 17',
      date: 'Read Oct 30, 2026',
      image: 'https://picsum.photos/seed/floppy-lantern/600/400',
      href: '/demo/the-lantern-keeper',
    },
    {
      key: 'today',
      label: 'Today',
      title: 'The Lantern Keeper',
      meta: 'Chapter 18 · 32min',
      date: 'Read today',
      image: 'https://picsum.photos/seed/floppy-lantern/600/400',
      href: '/demo/the-lantern-keeper',
    },
  ],
  game: [
    {
      key: 'first-play',
      label: 'First Play',
      title: 'Hades II',
      meta: '8h 20min played',
      date: 'Started May 14, 2026',
      image: 'https://picsum.photos/seed/floppy-hades/600/400',
      href: '/demo/hades-two',
    },
    {
      key: 'last-play',
      label: 'Last Play',
      title: 'Hades II',
      meta: '1h 54min played',
      date: 'Played yesterday',
      image: 'https://picsum.photos/seed/floppy-hades/600/400',
      href: '/demo/hades-two',
    },
    {
      key: 'today',
      label: 'Today',
      title: 'Hades II',
      meta: 'Surface run',
      date: 'Played today',
      image: 'https://picsum.photos/seed/floppy-hades/600/400',
      href: '/demo/hades-two',
    },
  ],
};

function demoSummaryFor(types) {
  if (!types.length) return summaries.all;
  if (types.length === 1) return summaries[types[0]] || summaries.all;
  const parts = types.map(type => summaries[type]).filter(Boolean);
  if (!parts.length) return summaries.all;
  const total = parts.reduce((sum, part) => sum + part.total, 0);
  const completed = parts.reduce((sum, part) => sum + part.completed, 0);
  const totalHours = parts.reduce((sum, part) => sum + part.totalHours, 0);
  const totalDays = parts.reduce((sum, part) => sum + part.totalDays, 0);
  const longest = Math.max(...parts.map(part => part.longestStreak));
  const current = Math.max(...parts.map(part => part.currentStreak));
  const score = parts.reduce((sum, part) => sum + part.averageScore, 0) / parts.length;
  return {
    ...summaries.all,
    total,
    completed,
    totalHours,
    totalDays,
    averageScore: Math.round(score * 10) / 10,
    mostActiveDay: parts[0].mostActiveDay,
    mostActiveDayLabel: parts[0].mostActiveDayLabel,
    mostActiveDayPercentage: parts[0].mostActiveDayPercentage,
    currentStreak: current,
    longestStreak: longest,
    longestStreakStart: parts[0].longestStreakStart,
    longestStreakDates: parts[0].longestStreakDates,
    typeLabel: 'titles',
    typeFlavor: 'stories, ideas, and worlds',
    comparison: {
      badge: '+18%',
      label: '+18%',
      state: 'up',
      periodLabel: 'last year',
      details: `${totalHours} hours this range`,
    },
  };
}

export default function StatisticsScreen({ navigate, onBack }) {
  const [range, setRange] = useState({
    selected: 'Last 12 Months',
    label: 'Last 12 months',
    dateLabel: 'Nov 5, 2025 – Nov 4, 2026',
    startDate: '2025-11-05',
    endDate: '2026-11-04',
  });
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedLabel, setUpdatedLabel] = useState('12 minutes ago');

  const model = useMemo(() => ({
    range: { ...range, options: ranges },
    mediaTypes: { selected: selectedTypes, options: mediaTypes },
    summary: demoSummaryFor(selectedTypes),
    highlights: selectedTypes.length === 1 ? (highlights[selectedTypes[0]] || highlights.all) : highlights.all,
    scaleMax: 10,
    refreshing,
    updatedLabel,
  }), [range, selectedTypes, refreshing, updatedLabel]);

  function refresh() {
    setRefreshing(true);
    setUpdatedLabel('just now');
    setTimeout(() => setRefreshing(false), 900);
  }

  return <Screen title="Statistics" subtitle="Your viewing and reading over time" onBack={onBack}>
    <StatisticsSummary model={model}
      palette={statisticsPalette}
      onChangeRange={next => setRange(next)}
      onChangeMediaTypes={types => setSelectedTypes(types)}
      onRefresh={refresh}
      onSelectHighlight={item => navigate('Detail', { item })}
      onRetry={refresh} />
    <Section title="Charts, comparison and taste">
      <Note surface={charts} />
    </Section>
  </Screen>;
}
