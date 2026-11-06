import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { CheckInState, PlaybackCard } from '../../../frontend/ui/PlaybackCard';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { createPlaybackTransport } from '../data/playbackTransport';
import { Note } from '../components/Note';
import { palette, playbackPalette, spacing } from '../theme';

export const surface = {
  id: 'PLAYBACK',
  status: 'ported',
  title: 'Now Playing and check-in',
  where: 'Home playback card and detail check-in state',
  note: 'The Home row renders the shared Now Playing card from /api/v1/playback/now-playing/ when signed in, and renders nothing when the server reports no active session — the same visibility rule as web Home. Stop/cancel stay absent until the native check-in transport exists, so no control is faked. The detail check-in state below still uses local demo state; wiring it to the server is outstanding. Web Home polls the server fragment and keeps the same card presentation.',
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

const POLL_MS = 30000;

export default function PlaybackSlot({ onOpenDetail }) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [cards, setCards] = useState([]);
  const [message, setMessage] = useState('');
  const mounted = useRef(true);

  useEffect(() => subscribeAuthSession(setSession), []);

  useEffect(() => {
    mounted.current = true;
    const transport = createPlaybackTransport({ auth: session });
    if (!transport) {
      setCards([]);
      return () => { mounted.current = false; };
    }
    let cancelled = false;
    const load = () => {
      transport.load().then(next => {
        if (!cancelled && mounted.current) {
          setCards(next);
          setMessage('');
        }
      }).catch(cause => {
        if (!cancelled && mounted.current) {
          setCards([]);
          setMessage(cause?.message || 'Now Playing could not be loaded from the server.');
        }
      });
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      mounted.current = false;
      clearInterval(timer);
    };
  }, [session]);

  if (!cards.length) {
    return message ? <Text style={styles.copy}>{message}</Text> : null;
  }

  return <View style={styles.root}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}>
      {cards.map(card => <View key={card.id} style={styles.card}>
        <PlaybackCard model={card} labels={labels} palette={playbackPalette}
          onOpenDetails={() => onOpenDetail?.(card)} />
      </View>)}
    </ScrollView>
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