import React, { useMemo, useState } from 'react';
import { StatisticsSummary } from '../../../frontend/ui/StatisticsSummary';
import { StatisticsCharts } from '../../../frontend/ui/StatisticsCharts';
import { Screen, Section } from '../components/Screen';
import { statisticsPalette } from '../theme';

export const surface = {
  id: 'STATISTICS',
  status: 'ported',
  title: 'Statistics summary, charts and activity overview',
  where: 'Statistics screen summary cards, highlights, range/media-type controls, charts and featured repeats',
  note: 'The summary hero, highlight cards, five summary cards, activity comparison and native chart families use the shared React Native presentation. Talent, taste signals, role leaders and studios remain legacy server fragments.',
};

const charts = {
  id: 'STATISTICS-CHARTS',
  status: 'ported',
  title: 'Statistics charts and featured repeats',
  where: 'Activity rhythm/history, hours, status/rating/completion charts and featured repeat player',
  note: 'The native chart renderer uses React Native primitives for every chart family. Values stay server-shaped; talent, taste signals, role leaders and studios remain legacy server fragments outside this chart port.',
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
  uniqueTitles: 23,
  uniqueMovies: 9,
  uniqueGames: 2,
  uniqueShows: 12,
  pctOfLibrary: 18.4,
  knownFor: [
    { label: 'Production Design' },
    { label: 'Drama' },
    { label: 'Sci-Fi' },
  ],
};

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

  const chartModel = useMemo(() => demoChartsFor(selectedTypes), [selectedTypes]);

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
    <Section title="Charts and featured repeats">
      <StatisticsCharts model={chartModel} palette={statisticsPalette} />
    </Section>
  </Screen>;
}

