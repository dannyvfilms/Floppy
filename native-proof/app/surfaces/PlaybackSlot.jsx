import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { CheckInState, PlaybackCard } from '../../../frontend/ui/PlaybackCard';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { createPlaybackTransport } from '../data/playbackTransport';
import { Note } from '../components/Note';
import { palette, playbackPalette, spacing } from '../theme';
import { playbackCardWidth } from '../../../frontend/ui/mediaCardSizing';
import { createSettingsTransport } from '../data/settingsTransport';

export const surface = {
  id: 'PLAYBACK',
  status: 'ported',
  title: 'Now Playing and check-in',
  where: 'Home playback card and detail check-in state',
  note: 'The Home row loads every active card from the session-only /api/v1/playback/home-cards/ endpoint and falls back to the older read-only single-card route. It uses the shared Lists MediaCard at 16:9, spanning three regular cards in compact mobile layout, two in comfortable mobile layout, and two on desktop. Manual check-ins offer Pause/Stop; check-in sessions offer Stop/Cancel. The detail check-in state below still uses local demo state; wiring it to the server is outstanding.',
};

const labels = {
  nowPlaying: 'Now Playing',
  playing: 'Playing',
  paused: 'Paused',
  stale: 'Last updated',
  pauseCheckIn: 'Pause check-in',
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
  const { width: viewportWidth } = useWindowDimensions();
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [cards, setCards] = useState([]);
  const [mobileGridLayout, setMobileGridLayout] = useState('compact');
  const [message, setMessage] = useState('');
  const [busyCard, setBusyCard] = useState(null);
  const mounted = useRef(true);
  const cardWidth = playbackCardWidth(viewportWidth, mobileGridLayout);

  useEffect(() => subscribeAuthSession(setSession), []);

  useEffect(() => {
    if (!session) {
      setMobileGridLayout('compact');
      return undefined;
    }
    let active = true;
    createSettingsTransport({ auth: session }).loadPreferences()
      .then(payload => {
        if (active) setMobileGridLayout(payload?.preferences?.mobile_grid_layout === 'comfortable'
          ? 'comfortable' : 'compact');
      })
      .catch(() => {});
    return () => { active = false; };
  }, [session]);

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

  async function act(card, action) {
    const transport = createPlaybackTransport({ auth: session });
    if (!transport) return;
    setBusyCard(`${card.id}:${action}`);
    setMessage('');
    try {
      await transport.act(card, action);
      const next = await transport.load();
      if (mounted.current) setCards(next);
    } catch (cause) {
      if (mounted.current) setMessage(cause?.message || 'The check-in could not be updated.');
    } finally {
      if (mounted.current) setBusyCard(null);
    }
  }

  return <View style={styles.root}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}>
      {cards.map(card => {
        const actions = Array.isArray(card.actions) ? card.actions : [];
        return <View key={card.id} style={[styles.card, { width: cardWidth }]}>
          <PlaybackCard model={card} labels={labels} palette={playbackPalette}
            width={cardWidth}
            onOpenDetails={() => onOpenDetail?.(card)}
            onPause={actions.includes('pause') ? () => act(card, 'pause') : undefined}
            onStop={actions.includes('finish') ? () => act(card, 'finish')
              : actions.includes('stop') ? () => act(card, 'stop') : undefined}
            onCancel={actions.includes('cancel') ? () => act(card, 'cancel') : undefined}
            busyAction={busyCard === `${card.id}:pause` ? 'pause'
              : busyCard === `${card.id}:finish` || busyCard === `${card.id}:stop` ? 'stop'
                : busyCard === `${card.id}:cancel` ? 'cancel' : null} />
        </View>;
      })}
    </ScrollView>
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
  card: { flexShrink: 0 },
  copy: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
