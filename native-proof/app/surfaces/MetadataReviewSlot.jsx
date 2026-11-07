import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import {
  EpisodeOrdering,
  MetadataMatchResults,
  TvProviderSwitch,
} from '../../../frontend/ui/MetadataReview';
import { Chip } from '../../../frontend/settings/Chip';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'METADATA-REVIEW',
  status: 'ported',
  title: 'Episode ordering, provider moves and metadata remaps',
  where: 'Detail metadata panel, episode ordering, TV provider switch and match results',
  note: 'The shared React presentation owns the episode-order chooser and review, the TV provider-move confirmation, and remap/library-move result choices. Native interactions use demo state; web mounts post to the existing Django routes.',
};

const colors = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  success: palette.success,
  successSoft: 'rgba(16, 185, 129, 0.2)',
  warning: palette.warning,
  warningSoft: 'rgba(245, 158, 11, 0.2)',
  accentSoft: 'rgba(99, 102, 241, 0.2)',
  danger: palette.danger,
  dangerSoft: 'rgba(239, 68, 68, 0.2)',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: radius.md,
  focusStyle: {},
};

const chipPalette = {
  badgeBorder: palette.border,
  badgeBackground: 'transparent',
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  interactiveStyle: {},
  focusStyle: {},
};

const activeChipPalette = {
  badgeBorder: palette.accentStrong,
  badgeBackground: palette.accentStrong,
  badgeText: '#ffffff',
  badgeHover: palette.accent,
  interactiveStyle: {},
  focusStyle: {},
};

const episodes = [
  { id: 't15', code: 'S5E15', title: 'Equinox', airDate: '1999-05-26' },
  { id: 't16', code: 'S5E16', title: 'Equinox, Part II', airDate: '1999-09-22' },
  { id: 't17', code: 'S5E17', title: 'Survival Instinct', airDate: '1999-10-06' },
  { id: 't18', code: 'S5E18', title: 'Barge of the Dead', airDate: '1999-11-03' },
];

const orderingModel = {
  mode: 'review',
  itemTitle: 'Star Trek: Voyager',
  itemUrl: '/demo/detail',
  currentOrderLabel: 'Original numbering',
  hasActiveOrder: true,
  canRevert: true,
  revertLabel: 'Original numbering',
  providerErrors: [],
  review: {
    label: 'Moving to TVDB (Aired order)',
    orderId: 1,
    token: 'demo-token',
    episodes,
    seasons: [{ number: 5, label: 'Season 5', watches: [101, 102, 103, 104] }],
    watches: [
      {
        id: 101, label: 'S5E15 · Equinox', seasonNumber: 5, episodeNumber: 15,
        title: 'Equinox', dateLabel: 'May 26, 1999', score: 8, status: 'Watched',
        notes: '', selected: ['t15'], pending: null, kind: 'matched',
      },
      {
        id: 102, label: 'S5E16 · Survival Instinct', seasonNumber: 5, episodeNumber: 16,
        title: 'Survival Instinct', dateLabel: 'Oct 6, 1999', score: null,
        status: 'Watched', notes: 'Imported before the two-part split.',
        selected: ['t17'], pending: null, kind: 'suggested',
      },
      {
        id: 103, label: 'S5E17 · Barge of the Dead', seasonNumber: 5, episodeNumber: 17,
        title: 'Barge of the Dead', dateLabel: 'Nov 3, 1999', score: null,
        status: 'Watched', notes: '', selected: [], pending: 't18', kind: 'needs',
      },
      {
        id: 104, label: 'S5E18 · Relativity', seasonNumber: 5, episodeNumber: 18,
        title: 'Relativity', dateLabel: 'No date', score: null, status: 'Watched',
        notes: '', selected: [], pending: null, kind: 'needs',
        archive: true,
      },
    ],
  },
};

const providerModel = {
  itemTitle: 'Star Trek: Voyager',
  sourceLabel: 'TMDB',
  targetLabel: 'TheTVDB',
  targetTitle: 'Star Trek: Voyager (1995)',
  seasons: 7,
  episodes: 168,
  missing: [],
  copy: 'This show is tracked on TMDB. Moving it keeps your status, ratings, notes and every watched episode, and only changes which provider (TheTVDB) supplies its seasons and episodes.',
  moveLabel: 'Move to TheTVDB',
};

const blockedProviderModel = {
  itemTitle: 'The Wire',
  sourceLabel: 'TVDB',
  targetLabel: 'TMDB',
  targetTitle: 'The Wire (2002)',
  seasons: 5,
  episodes: 58,
  missing: ['4x8', '4x9'],
  missingTitle: "TMDB is missing some of what you track, so this show can't be moved yet.",
  copy: 'This show is tracked on TheTVDB. Moving it keeps your status, ratings, notes and every watched episode, and only changes which provider (TMDB) supplies its seasons and episodes.',
  moveLabel: 'Move to TMDB',
};

const libraryMoveModel = {
  variant: 'libraryMove',
  query: 'voyager',
  targetSource: 'tvdb',
  targetMediaType: 'tv',
  returnUrl: '/demo/detail',
  results: [
    {
      id: '74205',
      title: 'Star Trek: Voyager',
      meta: 'TheTVDB · 1995',
      image: 'https://image.tmdb.org/t/p/w92/9n6WQ0pXJ5XwXQ0m7h7fX9yY0nV.jpg',
    },
    {
      id: '74206',
      title: 'Star Trek: Voyager — Documentary',
      meta: 'TheTVDB · 2001',
    },
  ],
};

const remapModel = {
  variant: 'remap',
  provider: 'tvdb',
  providerLabel: 'TheTVDB',
  query: 'voyager',
  returnUrl: '/demo/detail',
  results: [
    {
      id: '74205',
      title: 'Star Trek: Voyager',
      meta: 'TheTVDB',
      image: 'https://image.tmdb.org/t/p/w92/9n6WQ0pXJ5XwXQ0m7h7fX9yY0nV.jpg',
    },
    { id: '74207', title: 'Star Trek: Voyager — Season 5', meta: 'TheTVDB' },
  ],
};

const workflows = [
  { key: 'ordering', label: 'Episode ordering' },
  { key: 'provider', label: 'Provider move' },
  { key: 'match', label: 'Remap and move' },
];

export default function MetadataReviewSlot({ navigate }) {
  const [workflow, setWorkflow] = useState('ordering');
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState(null);

  function chooseMatch(result) {
    if (busyId) return;
    setBusyId(result.id);
    setMessage('');
    setTimeout(() => {
      setBusyId(null);
      setMessage(`Demo: ${result.title} would become the new tracking identity; status, ratings, notes and watched episodes are preserved.`);
    }, 600);
  }

  return <View style={styles.root}>
    <View style={styles.tabs}>
      {workflows.map(option => <Chip key={option.key} label={option.label}
        palette={option.key === workflow ? activeChipPalette : chipPalette}
        pressed={option.key === workflow}
        onPress={() => { setWorkflow(option.key); setMessage(''); }} />)}
    </View>

    {workflow === 'ordering' ? <EpisodeOrdering
      model={orderingModel}
      palette={colors}
      onOpenItem={() => navigate?.('Detail')}
      onRevert={() => setMessage('Demo: the previous episode order and every viewing would be restored.')}
      onCancel={() => setMessage('Demo: the chooser would reload without changing the order.')}
      onApply={() => setMessage('Demo: tracking moves to the reviewed episodes; unmapped rows stay archived under the original order.')} /> : null}

    {workflow === 'provider' ? <View style={styles.stack}>
      <TvProviderSwitch model={providerModel} palette={colors}
        onMove={() => setMessage('Demo: the show would move to TheTVDB and keep its status, ratings, notes and watched episodes.')}
        onCancel={() => setMessage('Demo: the detail page would reopen.')}
        onBack={() => setMessage('Demo: the detail page would reopen.')} />
      <TvProviderSwitch model={blockedProviderModel} palette={colors}
        onMove={() => setMessage('Demo: blocked until every tracked episode exists on the destination.')}
        onCancel={() => setMessage('Demo: the detail page would reopen.')}
        onBack={() => setMessage('Demo: the detail page would reopen.')} />
    </View> : null}

    {workflow === 'match' ? <View style={styles.stack}>
      <MetadataMatchResults model={libraryMoveModel} palette={colors}
        busyId={busyId} onChoose={chooseMatch} />
      <MetadataMatchResults model={remapModel} palette={colors}
        busyId={busyId} onChoose={chooseMatch} />
    </View> : null}

    {message ? <View accessibilityRole="status" style={styles.message}>
      <Text style={styles.messageText}>{message}</Text>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.lg },
  stack: { gap: spacing.lg },
  tabs: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  message: { borderWidth: 1, borderColor: palette.accent, borderRadius: radius.md,
    backgroundColor: 'rgba(99, 102, 241, 0.12)', padding: spacing.md },
  messageText: { color: palette.textSecondary, fontSize: 12, lineHeight: 17 },
});