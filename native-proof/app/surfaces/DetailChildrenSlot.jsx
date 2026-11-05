import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import {
  DetailChildren,
  DetailHistoryDialog,
} from '../../../frontend/ui/DetailChildren';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'CHILDREN',
  status: 'ported',
  title: 'Seasons, episodes and issue rows',
  where: 'Show, season, podcast and comic detail pages',
  note: 'Season rows, episode and issue rows, scores, watch/unwatch/drop/check-in actions, a Track action that opens the shared tracking dialog, spoiler reveal, ordering and history links use the shared React Native presentation. The web detail and episode pages keep their server-rendered rows, htmx actions and permissions.',
};

const childrenPalette = {
  ...palette,
  surfaceBorder: palette.border,
  mediaCard: {
    card: palette.surface,
    text: palette.text,
    textSecondary: palette.textSecondary,
    textMuted: palette.textMuted,
    border: palette.border,
    link: '#818cf8',
    star: palette.warning,
    chipBackground: 'rgba(24, 24, 27, 0.92)',
    chipText: '#ffffff',
    placeholder: palette.surfaceStrong,
    progressTrack: 'rgba(24, 24, 27, 0.6)',
    progressFill: palette.accent,
    progressPaused: 'rgba(99, 102, 241, 0.4)',
  },
  progress: {
    surface: palette.surface,
    surfaceMuted: palette.surfaceMuted,
    fill: palette.success,
    text: palette.text,
    textMuted: palette.textMuted,
  },
};

const labels = {
  seasons: 'Seasons',
  episodes: 'Episodes',
  issues: 'Issues',
  dropped: 'Dropped',
  notAired: 'Not aired yet',
  history: 'History',
  noHistory: 'No activity recorded yet.',
  noChildren: 'Nothing to show yet.',
  toggleOrder: 'Toggle row order',
  oldestFirst: 'Oldest first',
  newestFirst: 'Newest first',
  showAllThumbnails: 'Show all thumbnails',
  hideUnseenThumbnails: 'Hide unseen thumbnails',
  revealThumbnail: 'Reveal thumbnail',
  hiddenThumbnail: 'Thumbnail hidden',
  rate: 'Rate',
  close: 'Close',
};

const seasons = [
  {
    key: 'season-1',
    number: 1,
    title: 'Season 1',
    subtitle: '10 episodes · 2023',
    statusLabel: 'Completed',
    countLabel: '10 / 10 watched',
    percent: 100,
    dropped: false,
    actions: [{ key: 'drop', label: 'Drop season' }],
  },
  {
    key: 'season-2',
    number: 2,
    title: 'Season 2',
    subtitle: '10 episodes · 2024',
    statusLabel: 'In progress',
    countLabel: '6 / 10 watched',
    percent: 60,
    dropped: false,
    actions: [{ key: 'drop', label: 'Drop season' }],
  },
  {
    key: 'season-3',
    number: 3,
    title: 'Season 3',
    subtitle: '8 episodes · 2026',
    statusLabel: 'Planning',
    countLabel: '0 / 8 watched',
    percent: 0,
    dropped: true,
    actions: [{ key: 'restore', label: 'Restore season' }],
  },
];

function episode(key, number, title, overrides = {}) {
  return {
    key,
    number,
    code: `S02E${String(number).padStart(2, '0')}`,
    title,
    dateLabel: number <= 8 ? `Oct ${number + 2}, 2024` : 'Nov 2026',
    runtime: '48m',
    image: {
      src: `https://picsum.photos/seed/floppy-orbit-e${number}/640/360`,
      fallback: '',
      source: 'primary',
    },
    watched: false,
    dropped: false,
    unreleased: false,
    collectedLabel: null,
    score: null,
    scaleMax: 10,
    history: { summary: '' },
    historyRows: [],
    ...overrides,
  };
}

const initialEpisodes = [
  episode('s2e1', 1, 'A Quiet Arrival', {
    watched: true,
    collectedLabel: 'Collected',
    score: 8,
    history: { summary: 'Watched Oct 4 · 2× watched' },
    historyRows: [
      { dateLabel: 'Oct 4, 2024', actionLabel: 'Watched', score: 8 },
      { dateLabel: 'Mar 18, 2024', actionLabel: 'Watched', score: null },
    ],
  }),
  episode('s2e2', 2, 'The Relay', {
    watched: true,
    score: 7.5,
    history: { summary: 'Watched Oct 5' },
    historyRows: [{ dateLabel: 'Oct 5, 2024', actionLabel: 'Watched', score: 7.5 }],
  }),
  episode('s2e3', 3, 'Signal Lost', {
    watched: true,
    score: 8.5,
    history: { summary: 'Watched Oct 6' },
    historyRows: [{ dateLabel: 'Oct 6, 2024', actionLabel: 'Watched', score: 8.5 }],
  }),
  episode('s2e4', 4, 'The Long Night', {
    watched: true,
    score: 9.5,
    history: { summary: 'Watched Oct 7 · Note' },
    historyRows: [{
      dateLabel: 'Oct 7, 2024',
      actionLabel: 'Watched',
      score: 9.5,
      note: 'The station loses contact with the relay and the crew has to decide whether to wait or burn the last of the fuel.',
    }],
  }),
  episode('s2e5', 5, 'Six Years', {
    watched: true,
    score: 9,
    history: { summary: 'Watched Oct 8' },
    historyRows: [{ dateLabel: 'Oct 8, 2024', actionLabel: 'Watched', score: 9 }],
  }),
  episode('s2e6', 6, 'Halcyon', {
    watched: true,
    history: { summary: 'Watched Oct 9' },
    historyRows: [{ dateLabel: 'Oct 9, 2024', actionLabel: 'Watched', score: null }],
  }),
  episode('s2e7', 7, 'The Outer Ring', {
    score: 9,
    history: { summary: 'Not watched' },
    historyRows: [],
  }),
  episode('s2e8', 8, 'Drift', {
    history: { summary: 'Not watched' },
  }),
  episode('s2e9', 9, 'The Message', {
    dateLabel: 'Nov 2026',
    history: { summary: 'Not watched' },
  }),
  episode('s2e10', 10, 'Decay', {
    dateLabel: 'Nov 2026',
    runtime: null,
    unreleased: true,
    history: { summary: 'Not aired yet' },
  }),
];

function issue(key, number, title, overrides = {}) {
  return {
    key,
    number,
    code: `Issue #${number}`,
    title,
    dateLabel: `May ${number + 1}, 2026`,
    image: {
      src: `https://picsum.photos/seed/floppy-lantern-${number}/640/360`,
      fallback: '',
      source: 'primary',
    },
    watched: false,
    checkedIn: false,
    dropped: false,
    unreleased: false,
    score: null,
    scaleMax: 10,
    history: { summary: '' },
    historyRows: [],
    ...overrides,
  };
}

const initialIssues = [
  issue('issue-12', 12, 'The Lantern Archive', {
    watched: true,
    score: 9,
    history: { summary: 'Read May 13' },
    historyRows: [{ dateLabel: 'May 13, 2026', actionLabel: 'Read', score: 9 }],
  }),
  issue('issue-13', 13, 'A Door Left Open', {
    history: { summary: 'Not read' },
  }),
  issue('issue-14', 14, 'The Last Panel', {
    dateLabel: 'June 2026',
    unreleased: true,
    history: { summary: 'Not aired yet' },
  }),
];

function episodeActions(item) {
  if (item.unreleased) return [{ key: 'history', label: 'History' }];
  const actions = [
    item.watched
      ? { key: 'unwatch', label: 'Unwatch' }
      : { key: 'watch', label: 'Watch' },
  ];
  actions.push({ key: 'track', label: 'Track' });
  actions.push({ key: 'history', label: 'History' });
  if (!item.watched) {
    actions.push(item.dropped
      ? { key: 'restore', label: 'Restore' }
      : { key: 'drop', label: 'Drop' });
  }
  return actions;
}

function issueActions(item) {
  if (item.unreleased) return [{ key: 'history', label: 'History' }];
  const actions = [
    item.watched
      ? { key: 'unread', label: 'Unread' }
      : { key: 'read', label: 'Read' },
    item.checkedIn
      ? { key: 'stop', label: 'Stop check-in' }
      : { key: 'checkin', label: 'Check in' },
    { key: 'track', label: 'Track' },
    { key: 'history', label: 'History' },
  ];
  if (!item.watched) {
    actions.push(item.dropped
      ? { key: 'restore', label: 'Restore' }
      : { key: 'drop', label: 'Drop' });
  }
  return actions;
}

export default function DetailChildrenSlot({ onTrack }) {
  const [episodes, setEpisodes] = useState(initialEpisodes);
  const [issues, setIssues] = useState(initialIssues);
  const [seasonState, setSeasonState] = useState(seasons);
  const [obfuscate, setObfuscate] = useState(true);
  const [order, setOrder] = useState('asc');
  const [history, setHistory] = useState(null);

  const watchedCount = episodes.filter(item => item.watched).length;

  function updateEpisode(target, change) {
    setEpisodes(current => current.map(item => item.key === target.key ? change(item) : item));
  }

  function updateIssue(target, change) {
    setIssues(current => current.map(item => item.key === target.key ? change(item) : item));
  }

  function handleEpisodeAction(key, target) {
    if (key === 'track') {
      onTrack?.({ kind: 'episode', item: target });
      return;
    }
    updateEpisode(target, item => {
      if (key === 'watch') {
        return { ...item, watched: true, dropped: false, history: { summary: 'Watched today' } };
      }
      if (key === 'unwatch') {
        return { ...item, watched: false, history: { summary: 'Not watched' } };
      }
      if (key === 'drop') {
        return { ...item, dropped: true, history: { summary: 'Dropped' } };
      }
      if (key === 'restore') {
        return { ...item, dropped: false, history: { summary: 'Not watched' } };
      }
      return item;
    });
  }

  function handleIssueAction(key, target) {
    if (key === 'track') {
      onTrack?.({ kind: 'issue', item: target });
      return;
    }
    updateIssue(target, item => {
      if (key === 'read') {
        return { ...item, watched: true, dropped: false, history: { summary: 'Read today' } };
      }
      if (key === 'unread') {
        return { ...item, watched: false, history: { summary: 'Not read' } };
      }
      if (key === 'checkin') {
        return { ...item, checkedIn: true, history: { summary: 'Reading now' } };
      }
      if (key === 'stop') {
        return { ...item, checkedIn: false, history: { summary: 'Read today' } };
      }
      if (key === 'drop') {
        return { ...item, dropped: true, history: { summary: 'Dropped' } };
      }
      if (key === 'restore') {
        return { ...item, dropped: false, history: { summary: 'Not read' } };
      }
      return item;
    });
  }

  function handleRate(target, score) {
    setEpisodes(current => current.map(item => item.key === target.key ? { ...item, score } : item));
    setIssues(current => current.map(item => item.key === target.key ? { ...item, score } : item));
  }

  function handleSeasonAction(key, season) {
    setSeasonState(current => current.map(item => {
      if (item.key !== season.key) return item;
      if (key === 'drop') return { ...item, dropped: true, statusLabel: 'Dropped' };
      if (key === 'restore') {
        return {
          ...item,
          dropped: false,
          statusLabel: item.number === 1 ? 'Completed' : item.number === 3 ? 'Planning' : 'In progress',
        };
      }
      return item;
    }));
  }

  function handleShowAction(key, target) {
    if (String(target.key || '').startsWith('season-')) {
      handleSeasonAction(key, target);
      return;
    }
    handleEpisodeAction(key, target);
  }

  const showModel = {
    kind: 'show',
    seasons: seasonState.map(season => season.number === 2
      ? {
        ...season,
        countLabel: `${watchedCount} / 10 watched`,
        percent: Math.round((watchedCount / 10) * 100),
      }
      : season),
    obfuscation: { active: obfuscate, canToggle: true },
    episodes: episodes.map(item => ({
      ...item,
      obfuscated: obfuscate && !item.watched && !item.unreleased,
      canRate: !item.unreleased,
      actions: episodeActions(item),
    })),
  };

  const comicModel = {
    kind: 'comic',
    obfuscation: { active: obfuscate, canToggle: true },
    issues: issues.map(item => ({
      ...item,
      obfuscated: obfuscate && !item.watched && !item.unreleased,
      canRate: !item.unreleased,
      actions: issueActions(item),
    })),
  };

  const renderRating = ({ value, label, scaleMax, palette: ratingPalette, onSelect }) => (
    <RatingStars scaleMax={scaleMax} value={value} label={label} palette={ratingPalette}
      onSelect={onSelect}
      renderStar={lit => <Text style={[styles.star, {
        color: lit ? ratingPalette.lit : ratingPalette.unlit,
      }]}>★</Text>} />
  );

  return <View style={styles.root}>
    <DetailChildren model={showModel} labels={labels} palette={childrenPalette}
      order={order} onOrderChange={() => setOrder(current => current === 'asc' ? 'desc' : 'asc')}
      onOpenSeason={() => {}} onOpenChild={() => {}}
      onOpenHistory={item => setHistory({ title: item.title, rows: item.historyRows || [] })}
      onRate={handleRate} onAction={handleShowAction}
      onToggleObfuscation={setObfuscate} renderRating={renderRating} />
    <View style={[styles.divider, { backgroundColor: palette.border }]} />
    <DetailChildren model={comicModel} labels={labels} palette={childrenPalette}
      order={order}
      onOpenChild={() => {}}
      onOpenHistory={item => setHistory({ title: item.title, rows: item.historyRows || [] })}
      onRate={handleRate} onAction={handleIssueAction}
      onToggleObfuscation={setObfuscate} renderRating={renderRating} />
    <DetailHistoryDialog open={Boolean(history)} title={history?.title}
      rows={history?.rows || []} labels={labels} palette={childrenPalette}
      onClose={() => setHistory(null)} />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.lg },
  divider: { height: 1, marginVertical: spacing.sm },
  star: { fontSize: 16 },
});
