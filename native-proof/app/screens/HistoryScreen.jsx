import React, { useMemo, useState } from 'react';
import { HistoryFeed } from '../../../frontend/ui/HistoryFeed';
import { Screen } from '../components/Screen';
import { historyPalette } from '../theme';

export const surface = {
  id: 'HISTORY',
  status: 'ported',
  title: 'History feed and activity',
  where: 'History screen and per-item activity dialog',
  note: 'Bounded day groups, watched/read/played rows, month and filter controls, edit/delete actions, day summaries, lazy days, load more and loading/empty/error states use the shared React feed. The web History page keeps its server-rendered bounded fragments, cache refresh and Alpine filters as the fallback.',
};

const months = ['September 2026', 'October 2026', 'November 2026', 'December 2026'];

const labels = {
  mediaType: 'Media type',
  filters: 'Filter history',
  edit: 'Edit',
  delete: 'Delete',
};

function entry(overrides) {
  return {
    canEdit: true,
    canDelete: true,
    image: { src: null, fallback: '', source: 'primary' },
    ...overrides,
  };
}

function makeDays() {
  return [
    {
      key: '2026-11-04',
      weekday: 'Wednesday',
      dateLabel: 'November 4, 2026',
      entryCount: 3,
      runtimeLabel: '3h 58min',
      hasMore: false,
      remaining: 0,
      lazy: false,
      entries: [
        entry({
          key: 'episode-quiet-orbit-s2e4',
          mediaType: 'episode',
          title: 'The Quiet Orbit',
          subtitle: 'S02E04 · The Long Night',
          verb: 'Watched',
          when: 'Today at 9:42 PM',
          runtime: '48min',
          score: '8.5',
          status: 'Completed',
          href: '/demo/the-quiet-orbit',
          image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
          note: 'The station loses contact with the relay and the crew has to decide whether to wait for a signal or burn the last of the fuel. A quiet, patient episode with the best ending of the season.',
        }),
        entry({
          key: 'movie-dune-part-two',
          mediaType: 'movie',
          title: 'Dune: Part Two',
          verb: 'Watched',
          when: 'Today at 7:15 PM',
          runtime: '2h 46min',
          score: '9.0',
          status: 'Completed',
          href: '/demo/dune-part-two',
          image: { src: 'https://picsum.photos/seed/floppy-dune/400/600', fallback: '', source: 'primary' },
          note: '',
        }),
        entry({
          key: 'book-lantern-keeper',
          mediaType: 'book',
          title: 'The Lantern Keeper',
          verb: 'Read',
          when: 'Today at 6:10 PM',
          runtime: '32min',
          score: '7.5',
          status: 'In progress',
          href: '/demo/the-lantern-keeper',
          image: { src: 'https://picsum.photos/seed/floppy-lantern/400/600', fallback: '', source: 'primary' },
          note: 'Read 18 pages.',
        }),
      ],
    },
    {
      key: '2026-11-03',
      weekday: 'Tuesday',
      dateLabel: 'November 3, 2026',
      entryCount: 2,
      runtimeLabel: '2h 26min',
      hasMore: false,
      remaining: 0,
      lazy: false,
      entries: [
        entry({
          key: 'game-hades-two',
          mediaType: 'game',
          title: 'Hades II',
          verb: 'Played',
          when: 'Yesterday at 11:05 PM',
          runtime: '1h 54min',
          score: '8.8',
          status: 'In progress',
          href: '/demo/hades-two',
          image: { src: 'https://picsum.photos/seed/floppy-hades/400/600', fallback: '', source: 'primary' },
          note: 'Reached the third region with the Moonstone Axe. Two clears on the surface.',
        }),
        entry({
          key: 'music-night-drive',
          mediaType: 'music',
          title: 'Night Drive',
          altTitle: 'Night Drive (Deluxe)',
          subtitle: 'Synthwave · 6 plays',
          verb: 'Listened',
          when: 'Yesterday at 8:20 PM',
          runtime: '24min',
          score: '8.0',
          status: 'Completed',
          href: '/demo/night-drive',
          image: { src: 'https://picsum.photos/seed/floppy-night-drive/400/400', fallback: '', source: 'primary' },
          note: '',
        }),
      ],
    },
    {
      key: '2026-11-02',
      weekday: 'Monday',
      dateLabel: 'November 2, 2026',
      entryCount: 1,
      runtimeLabel: '52min',
      hasMore: false,
      remaining: 0,
      lazy: false,
      entries: [
        entry({
          key: 'podcast-signal-static-184',
          mediaType: 'podcast',
          title: 'Signal & Static',
          subtitle: 'Episode 184 · The Last Broadcast',
          verb: 'Listened',
          when: 'Monday at 7:40 AM',
          runtime: '52min',
          score: null,
          status: 'Completed',
          href: '/demo/signal-and-static',
          image: { src: 'https://picsum.photos/seed/floppy-signal/400/400', fallback: '', source: 'primary' },
          note: '',
        }),
      ],
    },
    {
      key: '2026-11-01',
      weekday: 'Sunday',
      dateLabel: 'November 1, 2026',
      entryCount: 3,
      runtimeLabel: '1h 12min',
      hasMore: false,
      remaining: 0,
      lazy: true,
      entries: [],
    },
    {
      key: '2026-10-31',
      weekday: 'Saturday',
      dateLabel: 'October 31, 2026',
      entryCount: 5,
      runtimeLabel: '2h 08min',
      hasMore: true,
      remaining: 3,
      lazy: false,
      entries: [
        entry({
          key: 'episode-quiet-orbit-s2e3',
          mediaType: 'episode',
          title: 'The Quiet Orbit',
          subtitle: 'S02E03 · Drift',
          verb: 'Watched',
          when: 'Saturday at 10:12 PM',
          runtime: '46min',
          score: '8.0',
          status: 'Completed',
          href: '/demo/the-quiet-orbit',
          image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
          note: '',
        }),
        entry({
          key: 'comic-saga-61',
          mediaType: 'comic',
          title: 'Saga',
          subtitle: 'Issue #61',
          verb: 'Read',
          when: 'Saturday at 4:35 PM',
          runtime: '22min',
          score: '9.0',
          status: 'Completed',
          href: '/demo/saga',
          image: { src: 'https://picsum.photos/seed/floppy-saga/400/600', fallback: '', source: 'primary' },
          note: '',
        }),
      ],
    },
  ];
}

const lazyEntries = [
  entry({
    key: 'episode-quiet-orbit-s2e2',
    mediaType: 'episode',
    title: 'The Quiet Orbit',
    subtitle: 'S02E02 · Static',
    verb: 'Watched',
    when: 'Sunday at 9:25 PM',
    runtime: '44min',
    score: '7.8',
    status: 'Completed',
    href: '/demo/the-quiet-orbit',
    image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
    note: '',
  }),
  entry({
    key: 'movie-arrival',
    mediaType: 'movie',
    title: 'Arrival',
    verb: 'Watched',
    when: 'Sunday at 6:10 PM',
    runtime: '1h 56min',
    score: '9.2',
    status: 'Completed',
    href: '/demo/arrival',
    image: { src: 'https://picsum.photos/seed/floppy-arrival/400/600', fallback: '', source: 'primary' },
    note: '',
  }),
];

const moreEntries = [
  entry({
    key: 'episode-quiet-orbit-s2e1',
    mediaType: 'episode',
    title: 'The Quiet Orbit',
    subtitle: 'S02E01 · Wake',
    verb: 'Watched',
    when: 'Saturday at 2:20 PM',
    runtime: '48min',
    score: '8.1',
    status: 'Completed',
    href: '/demo/the-quiet-orbit',
    image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
    note: '',
  }),
  entry({
    key: 'manga-frieren-112',
    mediaType: 'manga',
    title: 'Frieren: Beyond Journey’s End',
    subtitle: 'Chapter 112',
    verb: 'Read',
    when: 'Saturday at 12:05 PM',
    runtime: '14min',
    score: '9.4',
    status: 'Completed',
    href: '/demo/frieren',
    image: { src: 'https://picsum.photos/seed/floppy-frieren/400/600', fallback: '', source: 'primary' },
    note: '',
  }),
];

const summary = [
  { label: 'Active days', value: '5' },
  { label: 'Activity entries', value: '14' },
  { label: 'Tracked time', value: '10h 58min' },
  { label: 'Average per active day', value: '2h 12min' },
  { label: 'Longest streak', value: '5 days' },
  { label: 'Most active weekday', value: 'Wednesday' },
];

export default function HistoryScreen({ navigate, onBack }) {
  const [days, setDays] = useState(makeDays);
  const [monthIndex, setMonthIndex] = useState(2);
  const [filters, setFilters] = useState({ mode: 'activity', mediaTypes: [], activeCount: 0 });

  const model = useMemo(() => ({
    mode: filters.mode || 'activity',
    refreshing: false,
    summary,
    days,
    filters: {
      ...filters,
      rangeLabel: filters.from && filters.to ? `${filters.from} – ${filters.to}` : null,
    },
    options: {
      mediaTypes: [
        { value: 'tv', label: 'TV Show' },
        { value: 'movie', label: 'Movie' },
        { value: 'game', label: 'Game' },
        { value: 'music', label: 'Music' },
        { value: 'book', label: 'Book' },
        { value: 'comic', label: 'Comic' },
        { value: 'manga', label: 'Manga' },
        { value: 'podcast', label: 'Podcast' },
      ],
      genres: ['Science fiction', 'Drama', 'Synthwave'],
    },
    nav: {
      monthLabel: months[monthIndex],
      previousYear: { label: '2025', url: '/demo/history?year=2025' },
      previousMonth: { label: months[Math.max(monthIndex - 1, 0)].split(' ')[0], url: '/demo/history' },
      nextMonth: {
        label: months[Math.min(monthIndex + 1, months.length - 1)].split(' ')[0],
        url: '/demo/history',
        disabled: monthIndex >= months.length - 1,
      },
      currentMonth: { label: 'Today', url: '/demo/history', disabled: monthIndex === 2 },
    },
    pagination: null,
  }), [days, filters, monthIndex]);

  function navigateMonth(intent) {
    setMonthIndex(current => Math.max(0, Math.min(months.length - 1, current + (intent.direction || 0))));
  }

  function loadDay(day) {
    setDays(current => current.map(item => item.key === day.key
      ? { ...item, lazy: false, entries: lazyEntries }
      : item));
  }

  function loadMore(day) {
    setDays(current => current.map(item => item.key === day.key
      ? { ...item, entries: [...item.entries, ...moreEntries], hasMore: false, remaining: 0 }
      : item));
  }

  function deleteEntry(target) {
    setDays(current => current.map(day => ({
      ...day,
      entryCount: Math.max((day.entryCount || 0) - (day.entries.some(item => item.key === target.key) ? 1 : 0), 0),
      entries: day.entries.filter(item => item.key !== target.key),
    })));
  }

  function applyFilters(state) {
    const activeCount = (state.from ? 1 : 0) + (state.to ? 1 : 0)
      + (state.mediaTypes?.length ? 1 : 0) + (state.genre ? 1 : 0)
      + (state.impliedGenre ? 1 : 0) + (state.mode !== 'activity' ? 1 : 0);
    setFilters({ ...state, activeCount });
  }

  return <Screen title="History" subtitle="Everything you have watched, read and played" onBack={onBack}>
    <HistoryFeed
      model={model}
      labels={labels}
      palette={historyPalette}
      onNavigate={navigateMonth}
      onLoadMore={loadMore}
      onLoadDay={loadDay}
      onOpenEntry={item => navigate('Detail', { item })}
      onEditEntry={item => navigate('Detail', { item, edit: true })}
      onDeleteEntry={deleteEntry}
      onApplyFilters={applyFilters}
      onClearFilters={() => setFilters({ mode: 'activity', mediaTypes: [], activeCount: 0 })} />
  </Screen>;
}

