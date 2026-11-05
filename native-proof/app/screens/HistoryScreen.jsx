import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import {
  HistoryActivityDialog,
  HistoryDeleteDialog,
  HistoryEditDialog,
  HistoryFeed,
} from '../../../frontend/ui/HistoryFeed';
import { Screen } from '../components/Screen';
import { createHistoryTransport, historyEntriesFromPayload } from '../data/historyTransport';
import { historyPalette } from '../theme';

export const surface = {
  id: 'HISTORY',
  status: 'in_progress',
  title: 'History feed and activity',
  where: 'History screen and per-item activity dialog',
  note: 'Bounded day groups, lazy days, bounded load-more, filters and date ranges, session/activity, edit and delete dialogs, refresh/stale notices and loading/empty/error states use the shared React feed. Month navigation, filters, the cache banner, pagination and the activity dialog are adopted on the web, and the native screen loads bounded server days through historyTransport when signed in. Native edit, score and delete writes still use local demo state because the track-write contract is not mapped, so the surface stays in progress.',
};

const TODAY = '2026-11-04';
const INITIAL_DAY_ENTRIES = 2;
const DAY_ENTRIES_STEP = 2;
const LAZY_SEED = new Set(['2026-11-01', '2026-10-24', '2026-09-12']);

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];
const WEEKDAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const months = [
  { label: 'September 2026', prefix: '2026-09' },
  { label: 'October 2026', prefix: '2026-10' },
  { label: 'November 2026', prefix: '2026-11' },
  { label: 'December 2026', prefix: '2026-12' },
];
const CURRENT_MONTH_INDEX = 2;

const mediaTypeOptions = [
  { value: 'tv', label: 'TV Show' },
  { value: 'movie', label: 'Movie' },
  { value: 'anime', label: 'Anime' },
  { value: 'game', label: 'Game' },
  { value: 'music', label: 'Music' },
  { value: 'book', label: 'Book' },
  { value: 'comic', label: 'Comic' },
  { value: 'manga', label: 'Manga' },
  { value: 'podcast', label: 'Podcast' },
  { value: 'video', label: 'Video' },
  { value: 'boardgame', label: 'Board Game' },
];

const labels = {
  mediaType: 'Media type',
  filters: 'Filter history',
  edit: 'Edit',
  delete: 'Delete',
};

function dayNumber(dateKey) {
  const [year, month, day] = dateKey.split('-').map(Number);
  return Math.floor(Date.UTC(year, month - 1, day) / 86400000);
}

function dateParts(dateKey) {
  const [year, month, day] = dateKey.split('-').map(Number);
  const cell = new Date(Date.UTC(year, month - 1, day));
  return { year, month, day, weekday: WEEKDAY_NAMES[cell.getUTCDay()] };
}

function dateLabel(dateKey) {
  const { year, month, day } = dateParts(dateKey);
  return `${MONTH_NAMES[month - 1]} ${day}, ${year}`;
}

function timeLabel(time) {
  const [hour, minute] = String(time || '00:00').split(':').map(Number);
  const suffix = hour >= 12 ? 'PM' : 'AM';
  const shown = hour % 12 || 12;
  return `${shown}:${String(minute).padStart(2, '0')} ${suffix}`;
}

function whenLabel(dateKey, time) {
  const clock = timeLabel(time);
  const difference = dayNumber(dateKey) - dayNumber(TODAY);
  if (difference === 0) return `Today at ${clock}`;
  if (difference === -1) return `Yesterday at ${clock}`;
  const { month, day } = dateParts(dateKey);
  return `${MONTH_NAMES[month - 1]} ${day} at ${clock}`;
}

function minutesFromRuntime(value) {
  const match = /^(?:(\d+)h)?\s*(?:(\d+)min)?$/.exec(String(value || '').trim());
  if (!match) return 0;
  return (Number(match[1]) || 0) * 60 + (Number(match[2]) || 0);
}

function durationLabel(minutes) {
  if (!minutes) return '';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}min`;
  return rest ? `${hours}h ${rest}min` : `${hours}h`;
}

function makeEntry(input) {
  const entry = {
    canEdit: true,
    canDelete: true,
    genres: [],
    image: {
      src: `https://picsum.photos/seed/floppy-${input.seed || input.key}/400/600`,
      fallback: '',
      source: 'primary',
    },
    ...input,
    whenValue: `${input.date}T${input.time}`,
    when: input.when || whenLabel(input.date, input.time),
  };
  entry.runtimeMinutes = input.runtimeMinutes ?? minutesFromRuntime(input.runtime);
  entry.sessions = input.sessions || [{
    key: `${input.key}-session-1`,
    date: input.date,
    when: entry.when,
    label: input.verb,
    runtime: input.runtime,
    score: input.score,
    note: input.note,
  }];
  return entry;
}

function session(key, date, time, label, runtime, score, note) {
  return { key, date, when: whenLabel(date, time), label, runtime, score, note };
}

function demoEntries() {
  return [
    makeEntry({
      key: 'episode-quiet-orbit-s2e4', seed: 'orbit', mediaType: 'episode',
      date: '2026-11-04', time: '21:42', verb: 'Watched', runtime: '48min',
      score: 8.5, status: 'Completed', title: 'The Quiet Orbit',
      subtitle: 'S02E04 · The Long Night', genres: ['Science fiction', 'Drama'],
      releaseDate: '2026-10-30', href: '/demo/the-quiet-orbit',
      note: 'The station loses contact with the relay and the crew has to decide whether to wait for a signal or burn the last of the fuel. A quiet, patient episode with the best ending of the season.',
      sessions: [
        session('orbit-s2e4-1', '2026-11-04', '21:42', 'Watched', '48min', 8.5, 'First watch.'),
        session('orbit-s2e4-2', '2026-10-30', '20:10', 'Rewatched', '48min', 8.5, ''),
      ],
    }),
    makeEntry({
      key: 'movie-dune-part-two', seed: 'dune', mediaType: 'movie',
      date: '2026-11-04', time: '19:15', verb: 'Watched', runtime: '2h 46min',
      score: 9.0, status: 'Completed', title: 'Dune: Part Two',
      genres: ['Science fiction', 'Drama'], releaseDate: '2024-03-01',
      href: '/demo/dune-part-two', note: '',
    }),
    makeEntry({
      key: 'book-lantern-keeper', seed: 'lantern', mediaType: 'book',
      date: '2026-11-04', time: '18:10', verb: 'Read', runtime: '32min',
      score: 7.5, status: 'In progress', title: 'The Lantern Keeper',
      genres: ['Fantasy'], releaseDate: '2025-09-16', href: '/demo/the-lantern-keeper',
      note: 'Read 18 pages.',
      sessions: [
        session('lantern-1', '2026-11-04', '18:10', 'Read', '32min', 7.5, 'Read 18 pages.'),
        session('lantern-2', '2026-11-02', '21:20', 'Read', '24min', 7.5, 'Read 14 pages.'),
      ],
    }),
    makeEntry({
      key: 'game-hades-two', seed: 'hades', mediaType: 'game',
      date: '2026-11-03', time: '23:05', verb: 'Played', runtime: '1h 54min',
      score: 8.8, status: 'In progress', title: 'Hades II',
      genres: ['Action'], releaseDate: '2025-09-25', href: '/demo/hades-two',
      note: 'Reached the third region with the Moonstone Axe. Two clears on the surface.',
      sessions: [
        session('hades2-1', '2026-11-03', '23:05', 'Played', '1h 54min', 8.8, 'Two surface clears.'),
        session('hades2-2', '2026-11-01', '22:40', 'Played', '48min', 8.8, ''),
        session('hades2-3', '2026-09-21', '22:00', 'Played', '1h 20min', 8.6, ''),
      ],
    }),
    makeEntry({
      key: 'music-night-drive', seed: 'night-drive', mediaType: 'music',
      date: '2026-11-03', time: '20:20', verb: 'Listened', runtime: '24min',
      score: 8.0, status: 'Completed', title: 'Night Drive',
      altTitle: 'Night Drive (Deluxe)', subtitle: 'Synthwave · 6 plays',
      genres: ['Synthwave'], releaseDate: '2026-06-12', href: '/demo/night-drive',
      note: '',
      sessions: [
        session('night-drive-1', '2026-11-03', '20:20', 'Listened', '24min', 8.0, ''),
        session('night-drive-2', '2026-11-03', '19:10', 'Listened', '24min', 8.0, ''),
        session('night-drive-3', '2026-11-03', '18:05', 'Listened', '24min', 8.0, ''),
      ],
    }),
    makeEntry({
      key: 'podcast-signal-static-184', seed: 'signal', mediaType: 'podcast',
      date: '2026-11-02', time: '07:40', verb: 'Listened', runtime: '52min',
      score: null, status: 'Completed', title: 'Signal & Static',
      subtitle: 'Episode 184 · The Last Broadcast', genres: ['Drama'],
      releaseDate: '2026-11-01', href: '/demo/signal-and-static', note: '',
    }),
    makeEntry({
      key: 'episode-quiet-orbit-s2e3', seed: 'orbit', mediaType: 'episode',
      date: '2026-11-01', time: '21:25', verb: 'Watched', runtime: '46min',
      score: 8.0, status: 'Completed', title: 'The Quiet Orbit',
      subtitle: 'S02E03 · Drift', genres: ['Science fiction'], releaseDate: '2026-10-23',
      href: '/demo/the-quiet-orbit', note: '',
    }),
    makeEntry({
      key: 'movie-arrival', seed: 'arrival', mediaType: 'movie',
      date: '2026-11-01', time: '18:10', verb: 'Watched', runtime: '1h 56min',
      score: 9.2, status: 'Completed', title: 'Arrival',
      genres: ['Science fiction', 'Drama'], releaseDate: '2016-11-11',
      href: '/demo/arrival', note: '',
    }),
    makeEntry({
      key: 'comic-saga-61', seed: 'saga', mediaType: 'comic',
      date: '2026-11-01', time: '16:35', verb: 'Read', runtime: '22min',
      score: 9.0, status: 'Completed', title: 'Saga',
      subtitle: 'Issue #61', genres: ['Science fiction'], releaseDate: '2026-10-28',
      href: '/demo/saga', note: '',
    }),
    makeEntry({
      key: 'episode-quiet-orbit-s2e2', seed: 'orbit', mediaType: 'episode',
      date: '2026-10-31', time: '21:12', verb: 'Watched', runtime: '44min',
      score: 7.8, status: 'Completed', title: 'The Quiet Orbit',
      subtitle: 'S02E02 · Static', genres: ['Science fiction'], releaseDate: '2026-10-16',
      href: '/demo/the-quiet-orbit', note: '',
    }),
    makeEntry({
      key: 'manga-frieren-112', seed: 'frieren', mediaType: 'manga',
      date: '2026-10-31', time: '16:35', verb: 'Read', runtime: '14min',
      score: 9.4, status: 'Completed', title: 'Frieren: Beyond Journey’s End',
      subtitle: 'Chapter 112', genres: ['Fantasy'], releaseDate: '2026-10-25',
      href: '/demo/frieren', note: '',
    }),
    makeEntry({
      key: 'episode-quiet-orbit-s2e1', seed: 'orbit', mediaType: 'episode',
      date: '2026-10-31', time: '10:20', verb: 'Watched', runtime: '48min',
      score: 8.1, status: 'Completed', title: 'The Quiet Orbit',
      subtitle: 'S02E01 · Wake', genres: ['Science fiction'], releaseDate: '2026-10-09',
      href: '/demo/the-quiet-orbit', note: '',
    }),
    makeEntry({
      key: 'movie-blade-runner-2049', seed: 'blade-runner', mediaType: 'movie',
      date: '2026-10-30', time: '20:00', verb: 'Watched', runtime: '2h 44min',
      score: 9.1, status: 'Completed', title: 'Blade Runner 2049',
      genres: ['Science fiction'], releaseDate: '2017-10-06',
      href: '/demo/blade-runner-2049', note: '',
    }),
    makeEntry({
      key: 'game-hades', seed: 'hades', mediaType: 'game',
      date: '2026-10-30', time: '17:30', verb: 'Played', runtime: '1h 35min',
      score: 8.6, status: 'Completed', title: 'Hades',
      genres: ['Action'], releaseDate: '2020-09-17', href: '/demo/hades', note: '',
    }),
    makeEntry({
      key: 'book-project-hail-mary', seed: 'hail-mary', mediaType: 'book',
      date: '2026-10-28', time: '22:10', verb: 'Read', runtime: '41min',
      score: 8.7, status: 'In progress', title: 'Project Hail Mary',
      genres: ['Science fiction'], releaseDate: '2021-05-04',
      href: '/demo/project-hail-mary', note: 'Two chapters before bed.',
    }),
    makeEntry({
      key: 'podcast-signal-static-183', seed: 'signal', mediaType: 'podcast',
      date: '2026-10-24', time: '07:35', verb: 'Listened', runtime: '49min',
      score: null, status: 'Completed', title: 'Signal & Static',
      subtitle: 'Episode 183 · Dead Air', genres: ['Drama'], releaseDate: '2026-10-23',
      href: '/demo/signal-and-static', note: '',
    }),
    makeEntry({
      key: 'music-random-access-memories', seed: 'ram', mediaType: 'music',
      date: '2026-10-20', time: '19:00', verb: 'Listened', runtime: '30min',
      score: 8.4, status: 'Completed', title: 'Random Access Memories',
      subtitle: 'Electronic · 4 plays', genres: ['Synthwave'], releaseDate: '2013-05-17',
      href: '/demo/random-access-memories', note: '',
    }),
    makeEntry({
      key: 'movie-everything-everywhere', seed: 'eeaao', mediaType: 'movie',
      date: '2026-10-15', time: '20:30', verb: 'Watched', runtime: '2h 19min',
      score: 8.9, status: 'Completed', title: 'Everything Everywhere All at Once',
      genres: ['Science fiction', 'Drama'], releaseDate: '2022-03-25',
      href: '/demo/everything-everywhere', note: '',
    }),
    makeEntry({
      key: 'episode-the-bear-s3e1', seed: 'the-bear', mediaType: 'episode',
      date: '2026-10-08', time: '21:00', verb: 'Watched', runtime: '31min',
      score: 8.2, status: 'Completed', title: 'The Bear',
      subtitle: 'S03E01 · Tomorrow', genres: ['Drama'], releaseDate: '2026-06-27',
      href: '/demo/the-bear', note: '',
    }),
    makeEntry({
      key: 'comic-saga-60', seed: 'saga', mediaType: 'comic',
      date: '2026-10-01', time: '18:00', verb: 'Read', runtime: '23min',
      score: 8.8, status: 'Completed', title: 'Saga',
      subtitle: 'Issue #60', genres: ['Science fiction'], releaseDate: '2026-09-30',
      href: '/demo/saga', note: '',
    }),
    makeEntry({
      key: 'book-lantern-keeper-sep', seed: 'lantern', mediaType: 'book',
      date: '2026-09-30', time: '18:30', verb: 'Read', runtime: '26min',
      score: 7.5, status: 'In progress', title: 'The Lantern Keeper',
      genres: ['Fantasy'], releaseDate: '2025-09-16', href: '/demo/the-lantern-keeper',
      note: '',
    }),
    makeEntry({
      key: 'game-hades-two-sep', seed: 'hades', mediaType: 'game',
      date: '2026-09-21', time: '22:00', verb: 'Played', runtime: '1h 20min',
      score: 8.6, status: 'In progress', title: 'Hades II',
      genres: ['Action'], releaseDate: '2025-09-25', href: '/demo/hades-two', note: '',
    }),
    makeEntry({
      key: 'movie-dune-part-one', seed: 'dune', mediaType: 'movie',
      date: '2026-09-12', time: '19:30', verb: 'Watched', runtime: '2h 35min',
      score: 8.7, status: 'Completed', title: 'Dune',
      genres: ['Science fiction'], releaseDate: '2021-10-22', href: '/demo/dune', note: '',
    }),
    makeEntry({
      key: 'podcast-signal-static-182', seed: 'signal', mediaType: 'podcast',
      date: '2026-09-05', time: '07:30', verb: 'Listened', runtime: '47min',
      score: null, status: 'Completed', title: 'Signal & Static',
      subtitle: 'Episode 182 · Carrier Wave', genres: ['Drama'], releaseDate: '2026-09-04',
      href: '/demo/signal-and-static', note: '',
    }),
  ];
}

const genres = ['Action', 'Drama', 'Fantasy', 'Science fiction', 'Synthwave'];

function matchesType(entry, types) {
  return types.some(type => type === entry.mediaType || (type === 'tv' && entry.mediaType === 'episode'));
}

function entryDate(entry, mode) {
  return mode === 'release' ? entry.releaseDate : entry.date;
}

function buildSummary(entries, mode) {
  if (mode === 'release') {
    const releaseDays = new Set(entries.map(entry => entry.releaseDate)).size;
    const dates = [...new Set(entries.map(entry => entry.releaseDate))].sort();
    return [
      { label: 'Release days', value: String(releaseDays) },
      { label: 'Releases', value: String(entries.length) },
      { label: 'Range', value: dates.length ? `${dateLabel(dates[0])} – ${dateLabel(dates[dates.length - 1])}` : '—' },
    ];
  }
  const dates = [...new Set(entries.map(entry => entry.date))].sort();
  const totalMinutes = entries.reduce((sum, entry) => sum + entry.runtimeMinutes, 0);
  let longestStreak = 0;
  let currentStreak = 0;
  let previous = null;
  dates.forEach(dateKey => {
    const value = dayNumber(dateKey);
    currentStreak = previous !== null && value - previous === 1 ? currentStreak + 1 : 1;
    longestStreak = Math.max(longestStreak, currentStreak);
    previous = value;
  });
  const weekdayCounts = {};
  entries.forEach(entry => {
    const weekday = dateParts(entry.date).weekday;
    weekdayCounts[weekday] = (weekdayCounts[weekday] || 0) + 1;
  });
  const mostActive = Object.entries(weekdayCounts).sort((left, right) => right[1] - left[1])[0];
  return [
    { label: 'Active days', value: String(dates.length) },
    { label: 'Activity entries', value: String(entries.length) },
    { label: 'Tracked time', value: durationLabel(totalMinutes) || '—' },
    { label: 'Average per active day', value: durationLabel(Math.round(totalMinutes / Math.max(dates.length, 1))) || '—' },
    { label: 'Longest streak', value: dates.length ? `${longestStreak} days` : '—' },
    { label: 'Most active weekday', value: mostActive ? mostActive[0] : '—' },
  ];
}

export default function HistoryScreen({ navigate, onBack, transport: injectedTransport }) {
  const [transport] = useState(() => injectedTransport || createHistoryTransport());
  const [transportError, setTransportError] = useState('');
  const [entries, setEntries] = useState(demoEntries);
  const [monthIndex, setMonthIndex] = useState(CURRENT_MONTH_INDEX);
  const [filters, setFilters] = useState({ mode: 'activity', mediaTypes: [], genres: [], impliedGenres: [], activeCount: 0 });
  const [revealedLazy, setRevealedLazy] = useState(() => new Set());
  const [loadingDays, setLoadingDays] = useState(() => new Set());
  const [visibleCounts, setVisibleCounts] = useState({});
  const [refreshing, setRefreshing] = useState(true);
  const [refreshError, setRefreshError] = useState(false);
  const [activityEntry, setActivityEntry] = useState(null);
  const [editingEntry, setEditingEntry] = useState(null);
  const [deletingEntry, setDeletingEntry] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => setRefreshing(false), 900);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    transport.load({ limit: 30, maxEntriesPerDay: 10 })
      .then(payload => {
        if (!active) return;
        const loaded = historyEntriesFromPayload(payload);
        if (loaded.length) {
          setEntries(loaded);
          setRefreshing(false);
        }
      })
      .catch(error => {
        if (active) {
          setTransportError(error?.message || 'History could not be loaded from the server.');
        }
      });
    return () => { active = false; };
  }, [transport]);

  function beginRefresh() {
    setRefreshing(true);
    setRefreshError(false);
    setTimeout(() => setRefreshing(false), 700);
  }

  const mode = filters.mode || 'activity';
  const from = filters.from || '';
  const to = filters.to || '';

  const filtered = useMemo(() => {
    const monthPrefix = months[monthIndex].prefix;
    const hasRange = Boolean(from || to);
    return entries.filter(entry => {
      const dateKey = entryDate(entry, mode);
      if (!dateKey) return false;
      if (hasRange) {
        if (from && dateKey < from) return false;
        if (to && dateKey > to) return false;
      } else if (!dateKey.startsWith(monthPrefix)) {
        return false;
      }
      if (filters.mediaTypes?.length && !matchesType(entry, filters.mediaTypes)) return false;
      if (filters.genres?.length && !filters.genres.some(genre => (entry.genres || []).includes(genre))) return false;
      if (filters.impliedGenres?.length && !filters.impliedGenres.some(genre => (entry.genres || []).includes(genre))) return false;
      return true;
    });
  }, [entries, filters, monthIndex, mode, from, to]);

  const days = useMemo(() => {
    const groups = new Map();
    filtered.forEach(entry => {
      const key = entryDate(entry, mode);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(entry);
    });
    return [...groups.entries()]
      .sort((left, right) => right[0].localeCompare(left[0]))
      .map(([key, group]) => {
        const sorted = [...group].sort((left, right) => (right.time || '').localeCompare(left.time || ''));
        const parts = dateParts(key);
        const lazy = LAZY_SEED.has(key) && !revealedLazy.has(key);
        const visible = visibleCounts[key] ?? INITIAL_DAY_ENTRIES;
        const totalMinutes = sorted.reduce((sum, entry) => sum + entry.runtimeMinutes, 0);
        return {
          key,
          weekday: parts.weekday,
          dateLabel: dateLabel(key),
          entryCount: sorted.length,
          releaseCount: mode === 'release' ? sorted.length : undefined,
          runtimeLabel: mode === 'release' ? '' : durationLabel(totalMinutes),
          lazy,
          loading: loadingDays.has(key),
          hasMore: !lazy && sorted.length > visible,
          remaining: Math.max(sorted.length - visible, 0),
          loadingMore: false,
          entries: lazy ? [] : sorted.slice(0, visible),
          sessionEntries: sorted,
        };
      });
  }, [filtered, mode, visibleCounts, revealedLazy, loadingDays]);

  const summary = useMemo(() => buildSummary(filtered, mode), [filtered, mode]);

  const model = useMemo(() => {
    const hasRange = Boolean(from || to);
    const nav = hasRange ? {} : {
      monthLabel: months[monthIndex].label,
      previousMonth: { label: months[Math.max(monthIndex - 1, 0)].label.split(' ')[0], disabled: monthIndex === 0 },
      nextMonth: { label: months[Math.min(monthIndex + 1, months.length - 1)].label.split(' ')[0], disabled: monthIndex === months.length - 1 },
      currentMonth: { label: 'Today', disabled: monthIndex === CURRENT_MONTH_INDEX },
    };
    return {
      mode,
      refreshing,
      refreshError,
      summary,
      days,
      filters: {
        ...filters,
        rangeLabel: from || to ? `${from || 'earliest'} – ${to || 'today'}` : null,
      },
      options: {
        mediaTypes: mediaTypeOptions,
        genres,
      },
      nav,
      pagination: null,
    };
  }, [days, filters, monthIndex, mode, refreshing, refreshError, summary, from, to]);

  function handleNavigate(intent) {
    if (intent?.kind === 'current') {
      setMonthIndex(CURRENT_MONTH_INDEX);
    } else if (intent?.kind === 'month') {
      setMonthIndex(current => Math.max(0, Math.min(months.length - 1, current + (intent.direction || 0))));
    }
    setVisibleCounts({});
    setRevealedLazy(new Set());
  }

  function loadDay(day) {
    if (loadingDays.has(day.key)) return;
    setLoadingDays(current => new Set(current).add(day.key));
    setTimeout(() => {
      setLoadingDays(current => {
        const next = new Set(current);
        next.delete(day.key);
        return next;
      });
      setRevealedLazy(current => new Set(current).add(day.key));
    }, 450);
  }

  function loadMore(day) {
    setVisibleCounts(current => ({
      ...current,
      [day.key]: (current[day.key] ?? INITIAL_DAY_ENTRIES) + DAY_ENTRIES_STEP,
    }));
  }

  function applyFilters(state) {
    const activeCount = (state.from ? 1 : 0) + (state.to ? 1 : 0)
      + (state.mediaTypes?.length ? 1 : 0) + (state.genres?.length ? 1 : 0)
      + (state.impliedGenres?.length ? 1 : 0) + (state.mode !== 'activity' ? 1 : 0);
    setFilters({ ...state, activeCount });
    setVisibleCounts({});
    setRevealedLazy(new Set());
    beginRefresh();
  }

  function clearFilters() {
    setFilters({ mode: 'activity', mediaTypes: [], genres: [], impliedGenres: [], activeCount: 0 });
    setVisibleCounts({});
    setRevealedLazy(new Set());
    beginRefresh();
  }

  function openActivity(entry) {
    setActivityEntry(entry);
  }

  function openEditor(entry) {
    setActivityEntry(null);
    setEditingEntry(entry);
  }

  function requestDelete(entry) {
    setActivityEntry(null);
    setEditingEntry(null);
    setDeletingEntry(entry);
  }

  function saveEntry(entry, updates) {
    const [date, time = '00:00'] = String(updates.value || `${entry.date}T${entry.time}`).split('T');
    const when = whenLabel(date, time);
    setEntries(current => current.map(item => item.key === entry.key ? {
      ...item,
      date,
      time,
      whenValue: `${date}T${time}`,
      when,
      score: updates.score,
      status: updates.status || item.status,
      sessions: (item.sessions || []).map((itemSession, index) => index === 0
        ? { ...itemSession, date, when }
        : itemSession),
    } : item));
    setEditingEntry(null);
    beginRefresh();
  }

  function setEntryScore(entry, score) {
    setEntries(current => current.map(item => item.key === entry.key ? {
      ...item,
      score,
      sessions: (item.sessions || []).map((itemSession, index) => index === (item.sessions || []).length - 1
        ? { ...itemSession, score }
        : itemSession),
    } : item));
    setActivityEntry(current => current && current.key === entry.key ? { ...current, score } : current);
    beginRefresh();
  }

  function deleteEntry(entry) {
    setEntries(current => current.filter(item => item.key !== entry.key));
    setDeletingEntry(null);
    if (transport.mode === 'server' && entry.historyId != null && entry.mediaType) {
      transport.deleteRecord({
        mediaType: entry.mediaType,
        historyId: entry.historyId,
      }).catch(error => {
        setTransportError(error?.message || 'The server rejected the history change.');
      });
    }
    beginRefresh();
  }

  return <Screen title="History" subtitle="Everything you have watched, read and played" onBack={onBack}>
    {transportError
      ? <View style={styles.notice}>
        <Text accessibilityLiveRegion="polite" style={styles.noticeText}>{transportError}</Text>
      </View>
      : null}
    <HistoryFeed
      model={model}
      labels={labels}
      palette={historyPalette}
      onNavigate={handleNavigate}
      onLoadMore={loadMore}
      onLoadDay={loadDay}
      onRetryDay={loadDay}
      onOpenEntry={item => navigate('Detail', { item })}
      onOpenActivity={openActivity}
      onEditEntry={openEditor}
      onDeleteEntry={requestDelete}
      onApplyFilters={applyFilters}
      onClearFilters={clearFilters}
      onRefresh={beginRefresh} />
    <HistoryActivityDialog
      entry={activityEntry}
      labels={labels}
      palette={historyPalette}
      onClose={() => setActivityEntry(null)}
      onEdit={openEditor}
      onDelete={requestDelete}
      onSelectScore={score => setEntryScore(activityEntry, score)} />
    <HistoryEditDialog
      entry={editingEntry}
      labels={labels}
      palette={historyPalette}
      onClose={() => setEditingEntry(null)}
      onSave={saveEntry}
      onDelete={requestDelete} />
    <HistoryDeleteDialog
      entry={deletingEntry}
      labels={labels}
      palette={historyPalette}
      onClose={() => setDeletingEntry(null)}
      onConfirm={deleteEntry} />
  </Screen>;
}

const styles = StyleSheet.create({
  notice: {
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.4)',
    borderRadius: 8,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  noticeText: { color: '#f87171', fontSize: 13 },
});
