import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { CheckInState, PlaybackCard } from '../../../frontend/ui/PlaybackCard';
import { Note } from '../components/Note';
import { palette, playbackPalette, spacing } from '../theme';

export const surface = {
  id: 'PLAYBACK',
  status: 'ported',
  title: 'Now Playing and check-in',
  where: 'Home playback card and detail check-in state',
  note: 'The Home row renders the shared Now Playing card with artwork fallback, playing/paused status, live offset and progress, token-owned stop/cancel controls and stale-state labelling. The detail check-in state renders the shared phase, elapsed clock and ordered action intents. Demo data drives the native shell; the web Home row mounts the same card over the server fragments and the detail split button keeps htmx behind the shared state.',
};

const labels = {
  nowPlaying: 'Now Playing',
  playing: 'Playing',
  paused: 'Paused',
  stale: 'Last updated',
  stopCheckIn: 'Stop check-in',
  cancelCheckIn: 'Cancel check-in',
  openDetails: 'Open details',
  checkIn: 'Check-in',
  active: 'Check-in running',
  finishable: 'Ready to finish',
  session: 'Check-in running',
  pausedState: 'Check-in paused',
  elapsed: 'elapsed',
};

function seededCards() {
  const now = Math.floor(Date.now() / 1000);
  return [
    {
      id: 'orbit',
      title: 'The Quiet Orbit',
      episodeCode: 'S02E05',
      episodeTitle: 'Halcyon',
      subtitleLine: '',
      href: '/demo/detail',
      image: { src: '', alt: 'The Quiet Orbit' },
      status: 'playing',
      offsetSeconds: 1280,
      durationSeconds: 2880,
      updatedAtSeconds: now - 120,
      staleAfterSeconds: 45 * 60,
      progressPercent: 44,
      checkin: true,
    },
    {
      id: 'signal',
      title: 'Signal & Static',
      episodeCode: '',
      episodeTitle: 'Signal & Static',
      subtitleLine: 'Book · Chapter 12',
      href: '/demo/detail',
      image: { src: '', alt: 'Signal & Static' },
      status: 'paused',
      offsetSeconds: 1520,
      durationSeconds: 0,
      updatedAtSeconds: now - 240,
      staleAfterSeconds: 45 * 60,
      progressPercent: 0,
      checkin: true,
    },
  ];
}

export default function PlaybackSlot({ onOpenDetail }) {
  const [cards, setCards] = useState(seededCards);
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState('');

  function stop(card) {
    setBusy('stop');
    setTimeout(() => {
      setCards(current => current.map(entry => entry.id === card.id
        ? { ...entry, status: 'paused', updatedAtSeconds: Math.floor(Date.now() / 1000) }
        : entry));
      setBusy(null);
      setMessage(`${card.title} stopped. Its position stays saved.`);
    }, 250);
  }

  function cancel(card) {
    setBusy('cancel');
    setTimeout(() => {
      setCards(current => current.filter(entry => entry.id !== card.id));
      setBusy(null);
      setMessage(`${card.title} check-in cancelled.`);
    }, 250);
  }

  return <View style={styles.root}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}>
      {cards.map(card => <View key={card.id} style={styles.card}>
        <PlaybackCard model={card} labels={labels} palette={playbackPalette}
          onOpenDetails={() => onOpenDetail?.()}
          onStop={() => stop(card)}
          onCancel={() => cancel(card)}
          busyAction={busy} />
      </View>)}
    </ScrollView>
    {cards.length ? null : <Note surface={{ ...surface, status: 'in_progress', title: 'No active playback', note: 'The shared card is still placed here; this demo row is empty after both check-ins were stopped or cancelled.' }} />}
    {message ? <Text style={styles.copy}>{message}</Text> : null}
  </View>;
}

const startedAt = Math.floor(Date.now() / 1000) - 754;

export function CheckInStateSlot() {
  const [state, setState] = useState({ phase: 'active', message: '' });
  const actions = state.phase === 'active'
    ? [{ key: 'pause', label: 'Pause' }, { key: 'cancel', label: 'Cancel check-in' }, { key: 'edit', label: 'Edit' }]
    : [{ key: 'resume', label: 'Resume S02E05' }, { key: 'edit', label: 'Edit' }];

  function act(action) {
    if (action.key === 'cancel') {
      setState({ phase: 'idle', message: 'Check-in cancelled.' });
      return;
    }
    if (action.key === 'pause') {
      setState({ phase: 'paused', message: 'Check-in paused; the saved position stays.' });
      return;
    }
    if (action.key === 'resume') {
      setState({ phase: 'active', message: 'Check-in resumed.' });
      return;
    }
    setState(current => ({ ...current, message: 'The shared tracking dialog opens for this entry.' }));
  }

  if (state.phase === 'idle') {
    return <Note surface={{ ...surface, title: 'Check-in idle', note: state.message }} />;
  }

  return <View style={styles.root}>
    <CheckInState model={{
      phase: state.phase,
      code: 'S02E05',
      title: 'The Quiet Orbit',
      startedAtSeconds: startedAt,
    }} actions={actions} labels={labels} palette={playbackPalette} onAction={act} />
    {state.message ? <Text style={styles.copy}>{state.message}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  row: { gap: spacing.md, paddingRight: spacing.lg },
  card: { width: 300 },
  copy: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
