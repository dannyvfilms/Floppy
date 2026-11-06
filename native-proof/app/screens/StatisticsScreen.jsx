import React, { useEffect, useMemo, useState } from 'react';
import { StatisticsSummary, StatisticsState } from '../../../frontend/ui/StatisticsSummary';
import { StatisticsCharts } from '../../../frontend/ui/StatisticsCharts';
import {
  StatisticsComparison,
  StatisticsMediaTypeOverviews,
  StatisticsTalentSection,
} from '../../../frontend/ui/StatisticsSections';
import { Screen, Section } from '../components/Screen';
import { statisticsPalette } from '../theme';
import {
  createStatisticsTransport,
  flattenStatisticsModel,
} from '../data/statisticsTransport';

export const surface = {
  id: 'STATISTICS',
  status: 'in_progress',
  title: 'Statistics summary, charts, talent and per-media overviews',
  where: 'Statistics screen summary cards, highlights, range/media-type controls, charts, comparison, taste/talent, role/studio leaders, featured repeat and per-media-type overviews',
  note: 'Summary, controls, highlights, comparison, every chart family, talent and per-media overviews use the shared React Native components. Range, refresh and sort actions call the authenticated statistics endpoints, and loading, error/retry and empty states cover the summary, charts, talent and overview sections. Blockers: the select-featured-person endpoint returns server HTML and the transport has no action for it, so a server-mode role-leader selection highlights the row but cannot refresh the featured card; the person media strip has no shared model, so it is not rendered; loadTalent has no media-type parameter, so talent stays all-types while the selected media types change; the web page still renders talent through the server fragment, so shared talent adoption is incomplete there. iOS and Android runtime are unverified.',
};

const charts = {
  id: 'STATISTICS-CHARTS',
  status: 'ported',
  title: 'Statistics charts and featured repeats',
  where: 'Activity rhythm/history, hours, status/rating/completion charts and featured repeat player',
  note: 'The native chart renderer uses React Native primitives for every chart family. Values stay server-shaped; talent, taste signals, role leaders and studios remain legacy server fragments outside this chart port.',
};

const ranges = [
  { value: 'Today', label: 'Today' },
  { value: 'Yesterday', label: 'Yesterday' },
  { value: 'This Week', label: 'This week' },
  { value: 'Last 7 Days', label: 'Last 7 days' },
  { value: 'This Month', label: 'Month to date' },
  { value: 'Last 30 Days', label: 'Last 30 days' },
  { value: 'Last 90 Days', label: 'Last 90 days' },
  { value: 'This Year', label: 'Year to date' },
  { value: 'Last 6 Months', label: 'Last 6 months' },
  { value: 'Last 12 Months', label: 'Last 12 months' },
  { value: 'All Time', label: 'All time' },
];

function isoDay(value) {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

function formatDay(value) {
  return value.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function rangeDateLabel(startDate, endDate) {
  if (startDate === 'all') return 'Every tracked day';
  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(`${endDate}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return '';
  if (startDate === endDate) return formatDay(start);
  return `${formatDay(start)} – ${formatDay(end)}`;
}

function withRangeDates(option) {
  if (option.startDate !== undefined) {
    return {
      ...option,
      dateLabel: option.dateLabel || rangeDateLabel(option.startDate, option.endDate),
    };
  }
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let start = new Date(today);
  let end = new Date(today);
  switch (option.value) {
    case 'All Time':
      return { ...option, startDate: 'all', endDate: 'all', dateLabel: 'Every tracked day' };
    case 'Yesterday':
      start.setDate(start.getDate() - 1);
      end = new Date(start);
      break;
    case 'This Week': {
      const offset = (today.getDay() + 6) % 7;
      start.setDate(today.getDate() - offset);
      break;
    }
    case 'Last 7 Days':
      start.setDate(today.getDate() - 6);
      break;
    case 'This Month':
      start = new Date(today.getFullYear(), today.getMonth(), 1);
      break;
    case 'Last 30 Days':
      start.setDate(today.getDate() - 29);
      break;
    case 'Last 90 Days':
      start.setDate(today.getDate() - 89);
      break;
    case 'This Year':
      start = new Date(today.getFullYear(), 0, 1);
      break;
    case 'Last 6 Months':
      start.setMonth(today.getMonth() - 6);
      break;
    case 'Last 12 Months':
      start.setFullYear(today.getFullYear() - 1);
      break;
    default:
      break;
  }
  const startDate = isoDay(start);
  const endDate = isoDay(end);
  return { ...option, startDate, endDate, dateLabel: rangeDateLabel(startDate, endDate) };
}

const rangeOptions = ranges.map(withRangeDates);
const defaultRange = rangeOptions.find(option => option.value === 'Last 12 Months') || rangeOptions[0];

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

const chartMediaTypes = [
  { value: 'tv', label: 'TV Shows', color: '#10b981', seed: 3 },
  { value: 'movie', label: 'Movies', color: '#f97316', seed: 5 },
  { value: 'anime', label: 'Anime', color: '#3b82f6', seed: 7 },
  { value: 'game', label: 'Games', color: '#eab308', seed: 9 },
  { value: 'music', label: 'Music', color: '#fb7185', seed: 11 },
  { value: 'podcast', label: 'Podcasts', color: '#a855f7', seed: 13 },
  { value: 'book', label: 'Books', color: '#d946ef', seed: 15 },
  { value: 'comic', label: 'Comics', color: '#06b6d4', seed: 17 },
];

const statusOrder = ['Completed', 'In progress', 'Planning', 'Paused', 'Dropped'];
const statusColors = {
  Completed: '#10b981',
  'In progress': '#6366f1',
  Planning: '#87ceeb',
  Paused: '#f97316',
  Dropped: '#ef4444',
};

const statusCounts = {
  tv: { Completed: 84, 'In progress': 5, Planning: 4, Paused: 2, Dropped: 1 },
  movie: { Completed: 68, 'In progress': 2, Planning: 2, Paused: 1, Dropped: 1 },
  anime: { Completed: 34, 'In progress': 2, Planning: 1, Paused: 1, Dropped: 0 },
  game: { Completed: 12, 'In progress': 3, Planning: 4, Paused: 1, Dropped: 1 },
  music: { Completed: 58, 'In progress': 1, Planning: 2, Paused: 1, Dropped: 0 },
  podcast: { Completed: 16, 'In progress': 1, Planning: 1, Paused: 1, Dropped: 0 },
  book: { Completed: 18, 'In progress': 3, Planning: 4, Paused: 2, Dropped: 1 },
  comic: { Completed: 6, 'In progress': 1, Planning: 1, Paused: 1, Dropped: 1 },
};

const ratingCounts = {
  tv: [0, 0, 1, 2, 3, 6, 16, 28, 25, 15],
  movie: [0, 0, 1, 2, 4, 6, 12, 20, 18, 11],
  anime: [0, 0, 0, 1, 2, 3, 6, 10, 9, 7],
  game: [0, 0, 0, 1, 1, 2, 3, 6, 4, 4],
  music: [0, 1, 2, 4, 6, 8, 12, 14, 10, 5],
  podcast: [0, 0, 0, 1, 2, 3, 4, 5, 3, 1],
  book: [0, 0, 0, 1, 2, 4, 6, 7, 5, 3],
  comic: [0, 0, 0, 0, 1, 2, 2, 3, 1, 1],
};

const monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthWeights = [6, 7, 8, 7, 9, 8, 10, 9, 8, 10, 9, 9];
const weekdayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const weekdayWeights = [16, 14, 13, 12, 13, 14, 18];
const hourWeights = [1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 9, 10, 11, 10, 9, 9, 10, 12, 14, 15, 14, 11, 9, 5];
const hourLabels = Array.from({ length: 24 }, (_, hour) => (
  hour === 0 ? '12am' : hour < 12 ? `${hour}am` : hour === 12 ? '12pm' : `${hour - 12}pm`
));

const featuredRepeat = {
  name: 'Maya Chen',
  image: 'https://picsum.photos/seed/floppy-featured/300/300',
  source: 'tmdb',
  personId: 'maya-chen',
  bucket: 'Actors',
  uniqueTitles: 9,
  uniqueMovies: 3,
  uniqueGames: 1,
  uniqueShows: 5,
  pctOfLibrary: 2.6,
  knownFor: [
    { label: 'Production Design' },
    { label: 'Drama' },
    { label: 'Sci-Fi' },
  ],
};

function featuredFromPerson(entry, column) {
  if (!entry) return featuredRepeat;
  const titles = Number(entry.titles) || 0;
  const uniqueMovies = Math.max(1, Math.round(titles * 0.4));
  const uniqueGames = column?.bucket === 'actors' ? 1 : 0;
  const uniqueShows = Math.max(0, titles - uniqueMovies - uniqueGames);
  const libraryTotal = summaries.all.total || 0;
  return {
    name: entry.name,
    image: `https://picsum.photos/seed/floppy-${entry.personId}/300/300`,
    source: entry.source,
    personId: entry.personId,
    bucket: column?.label || '',
    uniqueTitles: titles,
    uniqueMovies,
    uniqueGames,
    uniqueShows,
    pctOfLibrary: libraryTotal ? Math.round((titles / libraryTotal) * 1000) / 10 : 0,
    knownFor: [
      { label: column?.label || 'Acting' },
      { label: 'Drama' },
      { label: 'Science Fiction' },
    ],
  };
}

function featuredFromServer(person) {
  if (!person) return null;
  return {
    name: person.name || '',
    image: person.image || '',
    source: person.source || '',
    personId: String(person.person_id || person.personId || ''),
    bucket: person.bucket || '',
    uniqueTitles: Number(person.unique_titles ?? person.uniqueTitles ?? 0),
    uniqueMovies: Number(person.unique_movies ?? person.uniqueMovies ?? 0),
    uniqueGames: Number(person.unique_games ?? person.uniqueGames ?? 0),
    uniqueShows: Number(person.unique_shows ?? person.uniqueShows ?? 0),
    pctOfLibrary: Number(person.pct_of_library ?? person.pctOfLibrary ?? 0),
    knownFor: (person.known_for_pills || person.knownFor || [])
      .map(pill => ({ label: pill?.label || '' }))
      .filter(pill => pill.label),
  };
}

function findRoleLeader(key) {
  const [source, personId] = String(key || '').split(':');
  for (const column of roleLeaderBuckets) {
    const entry = column.people.find(person => person.source === source && person.personId === personId);
    if (entry) return { entry, column };
  }
  return null;
}

function activeChartTypes(types) {
  return types.length ? types : chartMediaTypes.map(type => type.value);
}

function weightedSeries(total, weights) {
  const weightTotal = weights.reduce((sum, weight) => sum + weight, 0);
  return weights.map(weight => Math.round((total * weight / weightTotal) * 10) / 10);
}

function chartTotalHours(types) {
  const active = activeChartTypes(types);
  return active.reduce((sum, type) => sum + ((summaries[type] || {}).totalHours || 0), 0);
}

function rhythmFor(types) {
  const active = activeChartTypes(types);
  const matrix = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
  active.forEach(type => {
    const seed = (chartMediaTypes.find(entry => entry.value === type) || {}).seed || 3;
    for (let day = 0; day < 7; day += 1) {
      for (let hour = 0; hour < 24; hour += 1) {
        if (hour < 6) continue;
        const wave = Math.sin((day + 1) * (hour + 2) + seed) + 1.2;
        const evening = hour >= 18 && hour <= 22 ? 2.1 : hour >= 12 ? 1.2 : 0.7;
        const value = Math.round(wave * evening * seed);
        if (value > 0) matrix[day][hour] += value;
      }
    }
  });
  return matrix;
}

function heatmapFor(types) {
  const active = activeChartTypes(types);
  const seed = active.reduce((sum, type) => sum + ((chartMediaTypes.find(entry => entry.value === type) || {}).seed || 1), 0);
  const end = new Date(Date.UTC(2026, 10, 4));
  const mondayOffset = (end.getUTCDay() + 6) % 7;
  const lastMonday = new Date(end);
  lastMonday.setUTCDate(end.getUTCDate() - mondayOffset);
  const weekCount = 22;
  const startMonday = new Date(lastMonday);
  startMonday.setUTCDate(lastMonday.getUTCDate() - (weekCount - 1) * 7);
  const weeks = [];
  for (let week = 0; week < weekCount; week += 1) {
    const days = [];
    for (let day = 0; day < 7; day += 1) {
      const date = new Date(startMonday);
      date.setUTCDate(startMonday.getUTCDate() + week * 7 + day);
      const future = date.getTime() > end.getTime();
      const hash = (date.getUTCFullYear() * 372 + (date.getUTCMonth() + 1) * 31 + date.getUTCDate() + seed) % 11;
      days.push({
        key: date.toISOString().slice(0, 10),
        level: future || hash <= 2 ? 0 : 1 + (hash % 4),
        future,
        month: date.getUTCMonth(),
      });
    }
    weeks.push({ days });
  }
  const months = [];
  weeks.forEach(week => {
    const month = week.days[0].month;
    const previous = months[months.length - 1];
    if (!previous || previous.month !== month) {
      months.push({ month, label: monthLabels[month], span: 1 });
    } else {
      previous.span += 1;
    }
  });
  return {
    weeks,
    monthLabels: months,
    weekdayLabels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    rangeLabel: 'last 22 weeks',
  };
}

function seriesFor(types, weights) {
  return weightedSeries(chartTotalHours(types), weights);
}

function statusCompositionFor(types) {
  const active = activeChartTypes(types);
  const labels = [];
  const data = [];
  const colors = [];
  statusOrder.forEach(status => {
    const value = active.reduce((sum, type) => sum + ((statusCounts[type] || {})[status] || 0), 0);
    if (value > 0) {
      labels.push(status);
      data.push(value);
      colors.push(statusColors[status]);
    }
  });
  return { labels, data, colors };
}

function statusBreakdownFor(types) {
  const active = activeChartTypes(types);
  const rows = active.map(type => {
    const meta = chartMediaTypes.find(entry => entry.value === type);
    return {
      label: meta ? meta.label : type,
      color: meta ? meta.color : '#6366f1',
      total: (summaries[type] || {}).total || 0,
      statuses: statusCounts[type] || {},
    };
  });
  return {
    rows,
    columns: statusOrder.map(status => ({
      label: status,
      color: statusColors[status],
      completed: status === 'Completed',
    })),
  };
}

function completionFor(types) {
  const active = activeChartTypes(types);
  return {
    rows: active.map(type => {
      const meta = chartMediaTypes.find(entry => entry.value === type);
      const summary = summaries[type] || {};
      return {
        label: meta ? meta.label : type,
        color: meta ? meta.color : '#6366f1',
        completed: summary.completed || 0,
        total: summary.total || 0,
      };
    }),
  };
}

function demoChartsFor(types) {
  const active = activeChartTypes(types);
  const totalHours = chartTotalHours(types);
  const accent = types.length === 1
    ? ((chartMediaTypes.find(entry => entry.value === types[0]) || {}).color || '#6366f1')
    : '#6366f1';
  const distribution = active
    .map(type => {
      const meta = chartMediaTypes.find(entry => entry.value === type);
      return { label: meta ? meta.label : type, value: (summaries[type] || {}).totalHours || 0, color: meta ? meta.color : '#6366f1' };
    })
    .filter(entry => entry.value > 0);
  const ratings = Array.from({ length: 10 }, (_, index) => (
    active.reduce((sum, type) => sum + ((ratingCounts[type] || [])[index] || 0), 0)
  ));
  return {
    rhythm: {
      matrix: rhythmFor(types),
      weekdayLabels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    },
    heatmap: heatmapFor(types),
    mediaTypeHours: {
      title: 'Hours by Media Type',
      copy: 'Where your hours go.',
      labels: distribution.map(entry => entry.label),
      data: distribution.map(entry => entry.value),
      colors: distribution.map(entry => entry.color),
      totalLabel: 'total',
    },
    hoursByMonth: {
      title: 'Hours by Month',
      labels: monthLabels,
      data: seriesFor(types, monthWeights),
      color: accent,
    },
    hoursByWeekday: {
      title: 'Hours by Day of Week',
      labels: weekdayLabels,
      data: seriesFor(types, weekdayWeights),
      color: accent,
    },
    hoursByTimeOfDay: {
      title: 'Hours by Time of Day',
      labels: hourLabels,
      data: seriesFor(types, hourWeights),
      color: accent,
    },
    statusComposition: statusCompositionFor(types),
    ratingDistribution: {
      labels: Array.from({ length: 10 }, (_, index) => String(index + 1)),
      data: ratings,
      scaleMax: 10,
    },
    statusBreakdown: statusBreakdownFor(types),
    completion: completionFor(types),
    featured: featuredRepeat,
  };
}

const comparisonOptions = [
  { value: 'previous_period', label: 'Previous period' },
  { value: 'last_year', label: 'Last year' },
  { value: 'none', label: 'No comparison' },
];

const comparisonRows = {
  previous_period: [
    { key: 'tv', type: 'tv', label: 'TV Shows', color: '#10b981', currentLabel: '318h', comparisonLabel: '286h', deltaLabel: '+11%', state: 'up' },
    { key: 'movie', type: 'movie', label: 'Movies', color: '#f97316', currentLabel: '162h', comparisonLabel: '151h', deltaLabel: '+7%', state: 'up' },
    { key: 'anime', type: 'anime', label: 'Anime', color: '#3b82f6', currentLabel: '96h', comparisonLabel: '79h', deltaLabel: '+22%', state: 'up' },
    { key: 'game', type: 'game', label: 'Games', color: '#eab308', currentLabel: '104h', comparisonLabel: '108h', deltaLabel: '-4%', state: 'down' },
    { key: 'music', type: 'music', label: 'Music', color: '#fb7185', currentLabel: '34h', comparisonLabel: '33h', deltaLabel: '+3%', state: 'up' },
    { key: 'podcast', type: 'podcast', label: 'Podcasts', color: '#a855f7', currentLabel: '42h', comparisonLabel: '39h', deltaLabel: '+9%', state: 'up' },
    { key: 'book', type: 'book', label: 'Books', color: '#d946ef', currentLabel: '58h', comparisonLabel: '55h', deltaLabel: '+5%', state: 'up' },
    { key: 'comic', type: 'comic', label: 'Comics', color: '#06b6d4', currentLabel: '12h', comparisonLabel: '12h', deltaLabel: '0%', state: 'neutral' },
  ],
  last_year: [
    { key: 'tv', type: 'tv', label: 'TV Shows', color: '#10b981', currentLabel: '318h', comparisonLabel: '244h', deltaLabel: '+30%', state: 'up' },
    { key: 'movie', type: 'movie', label: 'Movies', color: '#f97316', currentLabel: '162h', comparisonLabel: '138h', deltaLabel: '+17%', state: 'up' },
    { key: 'anime', type: 'anime', label: 'Anime', color: '#3b82f6', currentLabel: '96h', comparisonLabel: '74h', deltaLabel: '+30%', state: 'up' },
    { key: 'game', type: 'game', label: 'Games', color: '#eab308', currentLabel: '104h', comparisonLabel: '92h', deltaLabel: '+13%', state: 'up' },
    { key: 'music', type: 'music', label: 'Music', color: '#fb7185', currentLabel: '34h', comparisonLabel: '29h', deltaLabel: '+17%', state: 'up' },
    { key: 'podcast', type: 'podcast', label: 'Podcasts', color: '#a855f7', currentLabel: '42h', comparisonLabel: '31h', deltaLabel: '+35%', state: 'up' },
    { key: 'book', type: 'book', label: 'Books', color: '#d946ef', currentLabel: '58h', comparisonLabel: '47h', deltaLabel: '+23%', state: 'up' },
    { key: 'comic', type: 'comic', label: 'Comics', color: '#06b6d4', currentLabel: '12h', comparisonLabel: '16h', deltaLabel: '-25%', state: 'down' },
  ],
  none: [
    { key: 'tv', type: 'tv', label: 'TV Shows', color: '#10b981', currentLabel: '318h' },
    { key: 'movie', type: 'movie', label: 'Movies', color: '#f97316', currentLabel: '162h' },
    { key: 'anime', type: 'anime', label: 'Anime', color: '#3b82f6', currentLabel: '96h' },
    { key: 'game', type: 'game', label: 'Games', color: '#eab308', currentLabel: '104h' },
    { key: 'music', type: 'music', label: 'Music', color: '#fb7185', currentLabel: '34h' },
    { key: 'podcast', type: 'podcast', label: 'Podcasts', color: '#a855f7', currentLabel: '42h' },
    { key: 'book', type: 'book', label: 'Books', color: '#d946ef', currentLabel: '58h' },
    { key: 'comic', type: 'comic', label: 'Comics', color: '#06b6d4', currentLabel: '12h' },
  ],
};

function demoComparisonFor(mode, types) {
  const rows = comparisonRows[mode] || comparisonRows.previous_period;
  const filtered = types.length ? rows.filter(row => types.includes(row.type)) : rows;
  const label = (comparisonOptions.find(option => option.value === mode) || comparisonOptions[0]).label;
  return {
    title: 'Comparison',
    copy: mode === 'none'
      ? 'Hours in this range. Choose a period to compare.'
      : `Hours in this range compared with ${label.toLowerCase()}.`,
    selected: mode,
    options: comparisonOptions,
    rows: filtered,
  };
}

const roleLeaderBuckets = [
  {
    bucket: 'actors',
    label: 'Actors',
    color: '#60a5fa',
    people: [
      { id: 'maya-chen', name: 'Maya Chen', source: 'tmdb', personId: 'maya-chen', plays: 18, time: '42h 10m', titles: 9 },
      { id: 'owen-park', name: 'Owen Park', source: 'tmdb', personId: 'owen-park', plays: 15, time: '36h 24m', titles: 8 },
      { id: 'theo-brooks', name: 'Theo Brooks', source: 'tmdb', personId: 'theo-brooks', plays: 12, time: '28h 05m', titles: 7 },
    ],
  },
  {
    bucket: 'actresses',
    label: 'Actresses',
    color: '#c084fc',
    people: [
      { id: 'lena-ortiz', name: 'Lena Ortiz', source: 'tmdb', personId: 'lena-ortiz', plays: 16, time: '38h 40m', titles: 8 },
      { id: 'ada-quinn', name: 'Ada Quinn', source: 'tmdb', personId: 'ada-quinn', plays: 13, time: '31h 12m', titles: 6 },
      { id: 'rae-mitchell', name: 'Rae Mitchell', source: 'tmdb', personId: 'rae-mitchell', plays: 11, time: '26h 48m', titles: 6 },
    ],
  },
  {
    bucket: 'directors',
    label: 'Directors',
    color: '#fb923c',
    people: [
      { id: 'reed-mason', name: 'Reed Mason', source: 'tmdb', personId: 'reed-mason', plays: 9, time: '22h 16m', titles: 5 },
      { id: 'ines-hart', name: 'Ines Hart', source: 'tmdb', personId: 'ines-hart', plays: 7, time: '17h 32m', titles: 4 },
      { id: 'jules-ward', name: 'Jules Ward', source: 'tmdb', personId: 'jules-ward', plays: 6, time: '14h 05m', titles: 3 },
    ],
  },
  {
    bucket: 'writers',
    label: 'Writers',
    color: '#34d399',
    people: [
      { id: 'ana-silva', name: 'Ana Silva', source: 'tmdb', personId: 'ana-silva', plays: 12, time: '27h 30m', titles: 7 },
      { id: 'noah-vance', name: 'Noah Vance', source: 'tmdb', personId: 'noah-vance', plays: 9, time: '21h 18m', titles: 5 },
      { id: 'clara-bell', name: 'Clara Bell', source: 'tmdb', personId: 'clara-bell', plays: 8, time: '19h 02m', titles: 4 },
    ],
  },
];

function demoRoleLeadersFor(sort, selectedKey) {
  const metric = entry => sort === 'time'
    ? entry.time
    : sort === 'titles'
      ? entry.titles
      : entry.plays;
  return {
    title: 'Role Leaders',
    copy: 'The actors, directors and writers you return to most.',
    selected: sort,
    sortOptions: [
      { value: 'plays', label: 'Plays' },
      { value: 'time', label: 'Time' },
      { value: 'titles', label: 'Titles' },
    ],
    columns: roleLeaderBuckets.map(bucket => ({
      ...bucket,
      entries: bucket.people.map(person => ({
        ...person,
        selected: `${person.source}:${person.personId}` === selectedKey,
        displayMetric: metric(person),
      })),
    })),
  };
}

function withPersonSelection(roleLeaders, selectedKey) {
  if (!roleLeaders?.columns) return roleLeaders;
  return {
    ...roleLeaders,
    columns: roleLeaders.columns.map(column => ({
      ...column,
      entries: (column.entries || []).map(entry => ({
        ...entry,
        selected: `${entry.source || ''}:${entry.personId || ''}` === selectedKey,
      })),
    })),
  };
}

const studioRows = {
  plays: [
    { name: 'A24', plays: 24, pct: 18, metricLabel: '24 plays' },
    { name: 'HBO', plays: 21, pct: 16, metricLabel: '21 plays' },
    { name: 'Netflix', plays: 18, pct: 14, metricLabel: '18 plays' },
    { name: 'Studio Trigger', plays: 13, pct: 10, metricLabel: '13 plays' },
    { name: 'Larian Studios', plays: 9, pct: 7, metricLabel: '9 plays' },
  ],
  time: [
    { name: 'HBO', time: '68h 12m', pct: 20, metricLabel: '68h 12m' },
    { name: 'A24', time: '52h 40m', pct: 16, metricLabel: '52h 40m' },
    { name: 'Netflix', time: '44h 15m', pct: 13, metricLabel: '44h 15m' },
    { name: 'Studio Trigger', time: '32h 08m', pct: 10, metricLabel: '32h 08m' },
    { name: 'Larian Studios', time: '28h 24m', pct: 9, metricLabel: '28h 24m' },
  ],
};

function demoStudioFootprintFor(sort) {
  return {
    title: 'Studio Footprint',
    copy: 'Studios that appear most often.',
    selected: sort,
    sortOptions: [
      { value: 'plays', label: 'Plays' },
      { value: 'time', label: 'Time' },
    ],
    delta: { label: '+6.4%', copy: 'studio appearances vs previous period', state: 'up' },
    studios: studioRows[sort] || studioRows.plays,
  };
}

const tasteSignals = {
  time: {
    genres: [
      { name: 'Drama', formattedDuration: '182h', pct: 31, color: '#3b82f6' },
      { name: 'Science Fiction', formattedDuration: '126h', pct: 22, color: '#8b5cf6' },
      { name: 'Comedy', formattedDuration: '94h', pct: 16, color: '#f59e0b' },
      { name: 'Thriller', formattedDuration: '78h', pct: 13, color: '#ef4444' },
      { name: 'Documentary', formattedDuration: '52h', pct: 9, color: '#10b981' },
    ],
    eras: [
      { label: '2020s', formattedDuration: '214h', pct: 38 },
      { label: '2010s', formattedDuration: '158h', pct: 28 },
      { label: '1990s', formattedDuration: '92h', pct: 16 },
      { label: '2000s', formattedDuration: '64h', pct: 11 },
      { label: '1980s', formattedDuration: '38h', pct: 7 },
    ],
  },
  plays: {
    genres: [
      { name: 'Drama', plays: 84, pct: 29, color: '#3b82f6' },
      { name: 'Science Fiction', plays: 66, pct: 23, color: '#8b5cf6' },
      { name: 'Comedy', plays: 49, pct: 17, color: '#f59e0b' },
      { name: 'Thriller', plays: 38, pct: 13, color: '#ef4444' },
      { name: 'Documentary', plays: 24, pct: 8, color: '#10b981' },
    ],
    eras: [
      { label: '2020s', plays: 96, pct: 36 },
      { label: '2010s', plays: 74, pct: 28 },
      { label: '1990s', plays: 46, pct: 17 },
      { label: '2000s', plays: 32, pct: 12 },
      { label: '1980s', plays: 18, pct: 7 },
    ],
  },
};

function demoTasteSignalsFor(sort) {
  const selected = tasteSignals[sort] || tasteSignals.time;
  return {
    title: 'Taste Signals',
    copy: 'What your library says about your taste.',
    selected: sort,
    sortOptions: [
      { value: 'time', label: 'Time' },
      { value: 'plays', label: 'Plays' },
    ],
    genres: selected.genres,
    eras: selected.eras,
  };
}

function overviewItem(title, subtitle, seed, value) {
  return {
    key: seed,
    title,
    subtitle,
    value,
    image: `https://picsum.photos/seed/floppy-${seed}/120/120`,
  };
}

const mediaOverviews = [
  {
    id: 'tv',
    typeValue: 'tv',
    typeLabel: 'TV Shows',
    title: 'Activity Overview',
    charts: [
      { key: 'tv-year', title: 'Episode Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [420, 486, 512, 548, 96], color: '#10b981' },
    ],
    panels: [
      {
        key: 'tv-most-played',
        title: 'Most Played',
        items: [
          overviewItem('The Quiet Orbit', '38h 12m · 48 episodes', 'tv-orbit', '9.1'),
          overviewItem('Harbour Lights', '29h 40m · 36 episodes', 'tv-harbour', '8.8'),
          overviewItem('Northbound', '24h 05m · 28 episodes', 'tv-north', '8.6'),
        ],
      },
      {
        key: 'tv-top-rated',
        title: 'Top Rated',
        items: [
          overviewItem('The Quiet Orbit', 'Drama · 2024', 'tv-orbit', '9.1'),
          overviewItem('Harbour Lights', 'Mystery · 2023', 'tv-harbour', '8.8'),
          overviewItem('Northbound', 'Adventure · 2025', 'tv-north', '8.6'),
        ],
      },
    ],
  },
  {
    id: 'movie',
    typeValue: 'movie',
    typeLabel: 'Movies',
    title: 'Activity Overview',
    charts: [
      { key: 'movie-year', title: 'Movie Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [38, 42, 47, 51, 12], color: '#f97316' },
    ],
    panels: [
      {
        key: 'movie-most-played',
        title: 'Most Played',
        items: [
          overviewItem('Dune: Part Two', '2h 46m · 4 plays', 'movie-dune', '4'),
          overviewItem('Arrival', '1h 56m · 3 plays', 'movie-arrival', '3'),
          overviewItem('The Batman', '2h 56m · 2 plays', 'movie-batman', '2'),
        ],
      },
      {
        key: 'movie-top-rated',
        title: 'Top Rated',
        items: [
          overviewItem('Dune: Part Two', 'Science Fiction · 2024', 'movie-dune', '9.2'),
          overviewItem('Arrival', 'Science Fiction · 2016', 'movie-arrival', '9.0'),
          overviewItem('Past Lives', 'Drama · 2023', 'movie-past-lives', '8.8'),
        ],
      },
    ],
  },
  {
    id: 'anime',
    typeValue: 'anime',
    typeLabel: 'Anime',
    title: 'Activity Overview',
    charts: [
      { key: 'anime-year', title: 'Episode Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [96, 118, 132, 146, 38], color: '#3b82f6' },
    ],
    panels: [
      {
        key: 'anime-most-played',
        title: 'Most Played',
        items: [
          overviewItem('Frieren: Beyond Journey’s End', '18h 20m · 28 episodes', 'anime-frieren', '28'),
          overviewItem('The Apothecary Diaries', '14h 05m · 24 episodes', 'anime-apothecary', '24'),
          overviewItem('Vinland Saga', '11h 36m · 24 episodes', 'anime-vinland', '24'),
        ],
      },
      {
        key: 'anime-top-rated',
        title: 'Top Rated',
        items: [
          overviewItem('Frieren: Beyond Journey’s End', 'Fantasy · 2024', 'anime-frieren', '9.4'),
          overviewItem('The Apothecary Diaries', 'Mystery · 2024', 'anime-apothecary', '9.1'),
          overviewItem('Vinland Saga', 'Action · 2023', 'anime-vinland', '8.9'),
        ],
      },
    ],
  },
  {
    id: 'game',
    typeValue: 'game',
    typeLabel: 'Video Games',
    title: 'Activity Overview',
    charts: [
      { key: 'game-year', title: 'Game Hours by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [48, 73, 92, 104, 64], color: '#eab308' },
      { key: 'game-month', title: 'Game Hours by Month', labels: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov'], data: [6, 9, 8, 12, 5], color: '#eab308' },
    ],
    panels: [
      {
        key: 'game-most-played',
        title: 'Most Played',
        items: [
          overviewItem('Hades II', '28h 14m this range', 'game-hades', '28h'),
          overviewItem('Balatro', '19h 40m this range', 'game-balatro', '19h'),
          overviewItem('Elden Ring', '16h 05m this range', 'game-elden', '16h'),
        ],
      },
      {
        key: 'game-platforms',
        title: 'Top Platforms',
        items: [
          overviewItem('PC', '42h · 8 games', 'game-pc', '42h'),
          overviewItem('Nintendo Switch', '26h · 5 games', 'game-switch', '26h'),
          overviewItem('PlayStation 5', '18h · 3 games', 'game-ps5', '18h'),
        ],
      },
    ],
  },
  {
    id: 'music',
    typeValue: 'music',
    typeLabel: 'Music',
    title: 'Activity Overview',
    charts: [
      { key: 'music-year', title: 'Music Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [148, 184, 212, 236, 62], color: '#fb7185' },
    ],
    panels: [
      {
        key: 'music-artists',
        title: 'Top Artists',
        roundImages: true,
        items: [
          overviewItem('Maya Chen', '6h 20m · 48 plays', 'music-maya', '48'),
          overviewItem('Low Tide', '4h 12m · 32 plays', 'music-low-tide', '32'),
          overviewItem('Northbound', '3h 48m · 26 plays', 'music-northbound', '26'),
        ],
      },
      {
        key: 'music-albums',
        title: 'Top Albums',
        items: [
          overviewItem('Afterglow', '3h 18m · 24 plays', 'music-afterglow', '24'),
          overviewItem('Night Water', '2h 44m · 19 plays', 'music-night-water', '19'),
          overviewItem('Signal Fires', '2h 05m · 16 plays', 'music-signal-fires', '16'),
        ],
      },
      {
        key: 'music-tracks',
        title: 'Top Tracks',
        items: [
          overviewItem('Quiet Cities', '42m · 12 plays', 'music-quiet-cities', '12'),
          overviewItem('Paper Moons', '36m · 10 plays', 'music-paper-moons', '10'),
          overviewItem('Half Light', '31m · 9 plays', 'music-half-light', '9'),
        ],
      },
      {
        key: 'music-decades',
        title: 'Top Decades',
        items: [
          overviewItem('2020s', '34h 12m · 84 plays', 'music-2020s', '84'),
          overviewItem('2010s', '18h 40m · 52 plays', 'music-2010s', '52'),
          overviewItem('1990s', '9h 06m · 24 plays', 'music-1990s', '24'),
        ],
      },
      {
        key: 'music-countries',
        title: 'Top Countries',
        items: [
          overviewItem('United States', '26h 18m · 68 plays', 'music-us', '68'),
          overviewItem('United Kingdom', '14h 42m · 44 plays', 'music-uk', '44'),
          overviewItem('Japan', '8h 12m · 22 plays', 'music-japan', '22'),
        ],
      },
    ],
  },
  {
    id: 'podcast',
    typeValue: 'podcast',
    typeLabel: 'Podcasts',
    title: 'Activity Overview',
    charts: [
      { key: 'podcast-year', title: 'Podcast Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [96, 124, 148, 172, 42], color: '#a855f7' },
    ],
    panels: [
      {
        key: 'podcast-most-played',
        title: 'Most Played',
        items: [
          overviewItem('The Long View', '8 plays', 'podcast-long-view', '8'),
          overviewItem('Design Notes', '7 plays', 'podcast-design-notes', '7'),
          overviewItem('Field Recordings', '5 plays', 'podcast-field', '5'),
        ],
      },
      {
        key: 'podcast-most-listened',
        title: 'Most Listened',
        items: [
          overviewItem('The Long View', '9h 12m · 8 plays', 'podcast-long-view', '9h'),
          overviewItem('Design Notes', '7h 40m · 7 plays', 'podcast-design-notes', '7h'),
          overviewItem('Field Recordings', '6h 05m · 5 plays', 'podcast-field', '6h'),
        ],
      },
      {
        key: 'podcast-longest',
        title: 'Longest Episodes',
        items: [
          overviewItem('The Long View', '1h 48m', 'podcast-long-view', '1h 48m'),
          overviewItem('Design Notes', '1h 22m', 'podcast-design-notes', '1h 22m'),
          overviewItem('Field Recordings', '1h 05m', 'podcast-field', '1h 05m'),
        ],
      },
    ],
  },
  {
    id: 'book',
    typeValue: 'book',
    typeLabel: 'Books',
    title: 'Activity Overview',
    facts: [
      { key: 'book-listening', label: 'Listening Time', value: '42h 18m', copy: 'Audiobook sessions in this range' },
    ],
    charts: [
      { key: 'book-year', title: 'Books Completed by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [12, 16, 18, 22, 6], color: '#d946ef' },
    ],
    panels: [
      {
        key: 'book-most-read',
        title: 'Most Read',
        items: [
          overviewItem('The Lantern Keeper', 'Chapter 18 · 32m today', 'book-lantern', '18'),
          overviewItem('A Map of Small Things', '412 pages · 14 sessions', 'book-map', '412'),
          overviewItem('The Glass Archive', '328 pages · 9 sessions', 'book-glass', '328'),
        ],
      },
      {
        key: 'book-authors',
        title: 'Top Authors',
        roundImages: true,
        items: [
          overviewItem('Iris Vale', '3 books · 1,120 pages', 'book-iris', '3'),
          overviewItem('Jon Bell', '2 books · 780 pages', 'book-jon', '2'),
          overviewItem('Mira Sol', '2 books · 640 pages', 'book-mira', '2'),
        ],
      },
      {
        key: 'book-genres',
        title: 'Top Genres',
        items: [
          overviewItem('Fantasy', '4 books · 1,280 pages', 'book-fantasy', '4'),
          overviewItem('Literary Fiction', '3 books · 920 pages', 'book-literary', '3'),
          overviewItem('Mystery', '2 books · 610 pages', 'book-mystery', '2'),
        ],
      },
      {
        key: 'book-top-rated',
        title: 'Top Rated',
        items: [
          overviewItem('The Lantern Keeper', 'Fantasy · 2025', 'book-lantern', '9.2'),
          overviewItem('A Map of Small Things', 'Literary Fiction · 2024', 'book-map', '8.9'),
          overviewItem('The Glass Archive', 'Mystery · 2023', 'book-glass', '8.7'),
        ],
      },
    ],
  },
  {
    id: 'comic',
    typeValue: 'comic',
    typeLabel: 'Comics',
    title: 'Activity Overview',
    charts: [
      { key: 'comic-year', title: 'Comics Finished by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [6, 8, 10, 12, 4], color: '#06b6d4' },
    ],
    panels: [
      {
        key: 'comic-most-read',
        title: 'Most Read',
        items: [
          overviewItem('Nova Drift', '12 issues', 'comic-nova', '12'),
          overviewItem('The Quiet Ward', '8 issues', 'comic-quiet-ward', '8'),
          overviewItem('Paper Kingdom', '6 issues', 'comic-paper', '6'),
        ],
      },
      {
        key: 'comic-genres',
        title: 'Top Genres',
        items: [
          overviewItem('Science Fiction', '3 series · 22 issues', 'comic-scifi', '22'),
          overviewItem('Fantasy', '2 series · 14 issues', 'comic-fantasy', '14'),
          overviewItem('Mystery', '1 series · 8 issues', 'comic-mystery', '8'),
        ],
      },
      {
        key: 'comic-top-rated',
        title: 'Top Rated',
        items: [
          overviewItem('Nova Drift', 'Science Fiction · 2025', 'comic-nova', '9.1'),
          overviewItem('The Quiet Ward', 'Mystery · 2024', 'comic-quiet-ward', '8.8'),
          overviewItem('Paper Kingdom', 'Fantasy · 2023', 'comic-paper', '8.5'),
        ],
      },
    ],
  },
  {
    id: 'video',
    typeValue: 'video',
    typeLabel: 'Video',
    title: 'Activity Overview',
    charts: [
      { key: 'video-year', title: 'Video Plays by Year', labels: ['2022', '2023', '2024', '2025', '2026'], data: [18, 24, 31, 38, 9], color: '#818cf8' },
    ],
    panels: [],
  },
];

function demoMediaOverviewsFor(types, rangeLabel) {
  const selected = types.length ? new Set(types) : null;
  return mediaOverviews
    .filter(overview => !selected || selected.has(overview.typeValue))
    .map(overview => ({ ...overview, rangeLabel }));
}


export default function StatisticsScreen({ navigate, onBack }) {
  const transport = useMemo(() => createStatisticsTransport(), []);
  const [range, setRange] = useState(defaultRange);
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [modelState, setModelState] = useState(transport.mode === 'server' ? 'loading' : 'ready');
  const [talentState, setTalentState] = useState(transport.mode === 'server' ? 'loading' : 'ready');
  const [reloadKey, setReloadKey] = useState(0);
  const [updatedLabel, setUpdatedLabel] = useState(transport.mode === 'server' ? '' : '12 minutes ago');
  const [compareMode, setCompareMode] = useState('previous_period');
  const [roleSort, setRoleSort] = useState('plays');
  const [studioSort, setStudioSort] = useState('plays');
  const [tasteSort, setTasteSort] = useState('time');
  const [selectedPersonKey, setSelectedPersonKey] = useState('tmdb:maya-chen');
  const [remoteModel, setRemoteModel] = useState(null);
  const [remoteTalent, setRemoteTalent] = useState(null);
  const [remoteFeatured, setRemoteFeatured] = useState(null);

  useEffect(() => {
    if (transport.mode !== 'server') {
      setRemoteModel(null);
      setModelState('ready');
      setRefreshing(false);
      return undefined;
    }
    let cancelled = false;
    setModelState(current => (current === 'ready' || current === 'refreshing' ? 'refreshing' : 'loading'));
    transport.loadModel({
      rangeName: range.selected,
      startDate: range.startDate,
      endDate: range.endDate,
      compareMode,
    }).then(data => {
      if (cancelled) return;
      setRemoteModel(data?.model || null);
      setModelState('ready');
      setRefreshing(false);
    }).catch(error => {
      if (cancelled) return;
      console.warn('Statistics model could not load', error);
      setModelState('error');
      setRefreshing(false);
    });
    return () => { cancelled = true; };
  }, [transport, reloadKey, range.selected, range.startDate, range.endDate, compareMode]);

  useEffect(() => {
    if (transport.mode !== 'server') {
      setRemoteTalent(null);
      setRemoteFeatured(null);
      setTalentState('ready');
      return undefined;
    }
    let cancelled = false;
    setTalentState(current => (current === 'ready' ? 'ready' : 'loading'));
    transport.loadTalent({
      rangeName: range.selected,
      startDate: range.startDate,
      endDate: range.endDate,
      compareMode,
    }).then(data => {
      if (cancelled) return;
      setRemoteTalent(data?.talent || null);
      setRemoteFeatured(featuredFromServer(data?.featuredPerson));
      if (data?.selectedPersonKey) setSelectedPersonKey(data.selectedPersonKey);
      setTalentState('ready');
    }).catch(error => {
      if (cancelled) return;
      console.warn('Statistics talent could not load', error);
      setTalentState('error');
    });
    return () => { cancelled = true; };
  }, [transport, reloadKey, range.selected, range.startDate, range.endDate, compareMode]);

  const remote = useMemo(
    () => (remoteModel ? flattenStatisticsModel(remoteModel, selectedTypes) : null),
    [remoteModel, selectedTypes],
  );

  const summary = remote?.summary || demoSummaryFor(selectedTypes);
  const remoteEmpty = Boolean(remoteModel)
    && !Number(summary.total || 0)
    && !(remote?.highlights || []).length;
  const loading = modelState === 'loading';
  const error = modelState === 'error';
  const empty = modelState === 'ready' && remoteEmpty;

  const featured = useMemo(() => {
    if (remoteFeatured) return remoteFeatured;
    if (transport.mode === 'server') return null;
    const found = findRoleLeader(selectedPersonKey);
    return found ? featuredFromPerson(found.entry, found.column) : featuredRepeat;
  }, [transport, remoteFeatured, selectedPersonKey]);

  const model = useMemo(() => ({
    range: { ...range, options: rangeOptions },
    mediaTypes: { selected: selectedTypes, options: mediaTypes },
    summary,
    highlights: remote
      ? remote.highlights || []
      : selectedTypes.length === 1
        ? (highlights[selectedTypes[0]] || highlights.all)
        : highlights.all,
    scaleMax: remote?.scaleMax || 10,
    loading,
    error,
    empty,
    refreshing: refreshing || modelState === 'refreshing',
    updatedLabel: remote?.updatedLabel || updatedLabel,
  }), [range, selectedTypes, summary, remote, loading, error, empty, refreshing, modelState, updatedLabel]);

  const chartModel = useMemo(() => {
    const demo = demoChartsFor(selectedTypes);
    return {
      ...demo,
      ...(remote?.charts || {}),
      featured,
      empty,
    };
  }, [remote, selectedTypes, featured, empty]);

  const comparisonModel = useMemo(() => {
    if (remoteModel) {
      const comparison = remote?.comparison || {};
      const rows = comparison.rows || [];
      const filtered = selectedTypes.length
        ? rows.filter(row => selectedTypes.includes(row.type))
        : rows;
      return { ...comparison, rows: filtered, empty: !filtered.length };
    }
    return demoComparisonFor(compareMode, selectedTypes);
  }, [remoteModel, remote, compareMode, selectedTypes]);

  const talentModel = useMemo(() => ({
    roleLeaders: remoteTalent?.roleLeaders
      ? withPersonSelection(remoteTalent.roleLeaders, selectedPersonKey)
      : demoRoleLeadersFor(roleSort, selectedPersonKey),
    studioFootprint: remoteTalent?.studioFootprint || demoStudioFootprintFor(studioSort),
    tasteSignals: remoteTalent?.tasteSignals || demoTasteSignalsFor(tasteSort),
  }), [remoteTalent, roleSort, selectedPersonKey, studioSort, tasteSort]);

  const mediaOverviewModel = useMemo(() => {
    if (remoteModel) {
      const all = remote?.overviews || [];
      const items = selectedTypes.length
        ? all.filter(overview => selectedTypes.includes(overview.typeValue))
        : all;
      return { items };
    }
    return { items: demoMediaOverviewsFor(selectedTypes, range.label) };
  }, [remoteModel, remote, selectedTypes, range.label]);

  const preferenceContext = useMemo(() => ({
    rangeName: range.selected,
    startDate: range.startDate,
    endDate: range.endDate,
    mediaType: selectedTypes.join(','),
  }), [range, selectedTypes]);

  function savePreference(action) {
    Promise.resolve(action).catch(error => {
      console.warn('Statistics preference could not be saved', error);
    });
  }

  function retry() {
    setReloadKey(value => value + 1);
  }

  function refresh() {
    setRefreshing(true);
    setUpdatedLabel('just now');
    savePreference(transport.requestRefresh({ rangeName: range.selected }));
    setReloadKey(value => value + 1);
  }

  function changeRange(option) {
    setRange(withRangeDates(option));
    setRefreshing(true);
  }

  function changeMediaTypes(types) {
    setSelectedTypes(types);
    savePreference(transport.saveMediaTypes({ mediaTypes: types }));
  }

  function changeCompareMode(mode) {
    setCompareMode(mode);
    savePreference(transport.saveCompareMode({ compareMode: mode }));
  }

  function changeRoleSort(sortBy) {
    setRoleSort(sortBy);
    transport.saveTopTalentSort({ sortBy, ...preferenceContext })
      .then(data => {
        if (data?.role_leaders) {
          setRemoteTalent(current => ({ ...(current || {}), roleLeaders: data.role_leaders }));
        }
      })
      .catch(error => console.warn('Top talent sort could not be saved', error));
  }

  function changeStudioSort(sortBy) {
    setStudioSort(sortBy);
    transport.saveStudioSort({ sortBy, ...preferenceContext })
      .then(data => {
        if (data?.studio_footprint) {
          setRemoteTalent(current => ({ ...(current || {}), studioFootprint: data.studio_footprint }));
        }
      })
      .catch(error => console.warn('Studio sort could not be saved', error));
  }

  function changeTasteSort(sortBy) {
    setTasteSort(sortBy);
    transport.saveGenreSort({ sortBy, ...preferenceContext })
      .then(data => {
        if (data?.taste_signals) {
          setRemoteTalent(current => ({ ...(current || {}), tasteSignals: data.taste_signals }));
        }
      })
      .catch(error => console.warn('Taste sort could not be saved', error));
  }

  function selectPerson(entry) {
    if (!entry?.source || !entry?.personId) return;
    setSelectedPersonKey(`${entry.source}:${entry.personId}`);
  }

  function openPerson(entry) {
    if (!entry?.source || !entry?.personId) return;
    navigate('People', {
      kind: 'person',
      source: entry.source,
      personId: entry.personId,
      slug: entry.personId,
    });
  }

  return <Screen title="Statistics" subtitle="Your viewing and reading over time" onBack={onBack}>
    <StatisticsSummary model={model}
      palette={statisticsPalette}
      onChangeRange={changeRange}
      onChangeMediaTypes={changeMediaTypes}
      onRefresh={refresh}
      onSelectHighlight={item => navigate('Detail', { item })}
      onRetry={retry} />
    {!loading && !error ? <React.Fragment>
      <Section title="Range comparison">
        <StatisticsComparison model={comparisonModel} palette={statisticsPalette}
          onCompareMode={changeCompareMode} onRetry={retry} />
      </Section>
      <Section title="Charts and featured repeats">
        <StatisticsCharts model={chartModel} palette={statisticsPalette}
          onSelectPerson={openPerson} />
      </Section>
      <Section title="Talent and taste">
        {talentState === 'ready'
          ? <StatisticsTalentSection model={talentModel} palette={statisticsPalette}
            onRoleSortChange={changeRoleSort}
            onStudioSortChange={changeStudioSort}
            onTasteSortChange={changeTasteSort}
            onSelectPerson={selectPerson} />
          : <StatisticsState kind={talentState === 'error' ? 'error' : 'loading'}
            palette={statisticsPalette} onRetry={retry} />}
      </Section>
      <Section title="Per-media activity overviews">
        <StatisticsMediaTypeOverviews model={mediaOverviewModel} palette={statisticsPalette}
          onSelectItem={item => navigate('Detail', { item })} />
      </Section>
    </React.Fragment> : null}
  </Screen>;
}

