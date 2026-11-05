import React, { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ProgressBreakdown } from '../../../frontend/ui/ProgressBreakdown';
import { ProgressCard } from '../../../frontend/ui/ProgressCard';
import { palette, progressDetailPalette, radius, spacing } from '../theme';

export const surface = {
  id: 'PROGRESS',
  status: 'in_progress',
  title: 'Detail progress card and breakdown',
  where: 'Show and season detail pages',
  note: 'The “Your Progress” card, rewatch glow and expandable season breakdown use the shared React Native presentation. The web keeps its htmx/Alpine modal shell and legacy card.',
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
    <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.backdrop}>
        <View accessibilityViewIsModal style={styles.dialog}>
          <View style={styles.header}>
            <Text style={styles.title} numberOfLines={1}>Your Progress · The Quiet Orbit</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={() => setOpen(false)} style={styles.close}>
              <Text style={styles.closeText}>×</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body}>
            <ProgressBreakdown model={model}
              palette={progressDetailPalette}
              cancelling={false}
              onCancelRewatch={() => setRewatching(false)} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0, 0, 0, 0.5)', padding: spacing.lg },
  dialog: { width: '100%', maxWidth: 672, maxHeight: '90%', overflow: 'hidden', borderRadius: radius.lg, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.background },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderBottomWidth: 1, borderBottomColor: palette.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  title: { flex: 1, color: palette.text, fontSize: 16, fontWeight: '600' },
  close: { alignItems: 'center', justifyContent: 'center', width: 32, height: 32, borderRadius: 16 },
  closeText: { color: palette.textMuted, fontSize: 22, lineHeight: 24 },
  body: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
});
