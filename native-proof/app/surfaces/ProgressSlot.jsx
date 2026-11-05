import React, { useState } from 'react';
import { View } from 'react-native';
import { ProgressCard } from '../../../frontend/ui/ProgressCard';
import { ProgressDialog } from '../../../frontend/ui/ProgressDialog';
import { progressDetailPalette } from '../theme';

export const surface = {
  id: 'PROGRESS',
  status: 'ported',
  title: 'Detail progress card and breakdown',
  where: 'Show and season detail pages',
  note: 'The “Your Progress” card, rewatch glow and expandable season breakdown use the shared React Native presentation. The web now mounts the shared card and dialog over the same htmx fragment endpoint, with the legacy Alpine card and modal as the server fallback.',
};

const labels = {
  yourProgress: 'Your Progress',
  caughtUp: 'Caught Up',
  aboutProgress: 'About your progress',
  progressTip: 'Your progress is how much of the show you have watched at least once. While you rewatch, a glowing line shows how far along the rewatch is.',
  openBreakdown: 'Open the season and episode breakdown',
  watched: 'Watched',
  of: 'of',
  episodes: 'episodes',
  left: 'left',
  expandAll: 'Expand all',
  collapseAll: 'Collapse all',
  toggleSeason: 'Toggle',
  dropped: 'Dropped',
  notAired: 'Not aired yet',
  episodeWatched: 'episode watched',
  episodesWatched: 'episodes watched',
  rewatched: 'Rewatched',
  rewatching: 'Rewatching',
  watchedAgain: 'Watched again',
  watchedLabel: 'Watched',
  notWatched: 'Not watched',
  notAiredYet: 'Not aired yet',
  noEpisodes: 'No episodes to show yet.',
  catalogueUnavailable: 'The episode list could not be loaded, so only the episodes you have watched are shown.',
  cancelRewatch: 'Cancel rewatch',
  cancelling: 'Cancelling…',
  loading: 'Loading…',
  loadError: 'Your progress could not be loaded. Close this and try again.',
};

const seasonOne = { number: 1, title: 'Season 1', url: '/demo/the-quiet-orbit/season/1', dropped: false, rewatching: false, catalogueMissing: false, watched: 10, total: 10, percent: 100, rewatchPercent: null, rewatchWatched: 0, episodes: Array.from({ length: 10 }, (_, index) => ({
  number: index + 1,
  title: `Episode ${index + 1}`,
  url: `/demo/the-quiet-orbit/season/1/episode/${index + 1}`,
  state: 'watched',
  rewatched: false,
})) };

const seasonTwo = { number: 2, title: 'Season 2', url: '/demo/the-quiet-orbit/season/2', dropped: false, rewatching: true, catalogueMissing: false, watched: 10, total: 12, percent: 83, rewatchPercent: 67, rewatchWatched: 8, episodes: Array.from({ length: 12 }, (_, index) => ({
  number: index + 1,
  title: `Episode ${index + 1}`,
  url: `/demo/the-quiet-orbit/season/2/episode/${index + 1}`,
  state: index < 10 ? 'watched' : 'unwatched',
  rewatched: index < 8,
})) };

const seasonThree = { number: 3, title: 'Season 3', url: '/demo/the-quiet-orbit/season/3', dropped: false, rewatching: false, catalogueMissing: false, watched: 4, total: 16, percent: 25, rewatchPercent: null, rewatchWatched: 0, episodes: Array.from({ length: 16 }, (_, index) => ({
  number: index + 1,
  title: `Episode ${index + 1}`,
  url: `/demo/the-quiet-orbit/season/3/episode/${index + 1}`,
  state: index < 4 ? 'watched' : index < 12 ? 'unwatched' : 'upcoming',
  rewatched: false,
})) };

function demoModel(rewatching) {
  const seasons = [seasonOne, seasonTwo, seasonThree];
  const summaryRewatch = rewatching
    ? { offset: 26.32, width: 21.05, percent: 67, label: 'Season 2 rewatch · 8/12 · 67%', season: 2, watched: 8, total: 12 }
    : null;
  return {
    runKey: rewatching ? 'demo-rewatch-run' : '',
    catalogueUnavailable: false,
    open: { 1: false, 2: true, 3: false },
    summary: {
      watched: 24,
      total: 38,
      left: 14,
      percent: 63,
      leftText: '14 left (11h 20m)',
      minutesLeftLabel: '11h 20m',
      caughtUp: false,
      rewatch: summaryRewatch,
    },
    seasons: rewatching
      ? seasons
      : seasons.map(season => season.number === 2
        ? { ...season, rewatching: false, rewatchPercent: null, rewatchWatched: 0, episodes: season.episodes.map(episode => ({ ...episode, rewatched: false })) }
        : season),
    labels,
  };
}

export default function ProgressSlot() {
  const [open, setOpen] = useState(false);
  const [rewatching, setRewatching] = useState(true);
  const model = demoModel(rewatching);
  return <View>
    <ProgressCard model={{
      percent: model.summary.percent,
      rewatch: model.summary.rewatch,
      caughtUp: model.summary.caughtUp,
    }} labels={labels} palette={progressDetailPalette} onOpen={() => setOpen(true)} />
    <ProgressDialog visible={open}
      title="Your Progress · The Quiet Orbit"
      model={model}
      labels={labels}
      palette={progressDetailPalette}
      cancelling={false}
      onClose={() => setOpen(false)}
      onCancelRewatch={() => setRewatching(false)} />
  </View>;
}
