import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from './Button';
import { MediaCard } from './MediaCard';

const defaultLabels = {
  nowPlaying: 'Now Playing',
  playing: 'Playing',
  paused: 'Paused',
  stale: 'Last updated',
  pauseCheckIn: 'Pause',
  stopCheckIn: 'Stop',
  cancelCheckIn: 'Cancel check-in',
  openDetails: 'Open details',
  checkIn: 'Check-in',
  active: 'Check-in running',
  finishable: 'Ready to finish',
  session: 'Check-in running',
  pausedState: 'Check-in paused',
  elapsed: 'elapsed',
};

const fallbackPalette = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceHover: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  link: '#818cf8',
  accent: '#6366f1',
  warning: '#f59e0b',
  danger: '#ef4444',
  chipBackground: 'rgba(24, 24, 27, 0.92)',
  chipText: '#ffffff',
  placeholder: '#3f3f46',
  progressTrack: 'rgba(24, 24, 27, 0.8)',
  progressFill: '#6366f1',
  pausedFill: '#f59e0b',
  focusStyle: {},
};

const buttonPalette = {
  radius: 9999,
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(239, 68, 68, 0.2)', hovered: 'rgba(239, 68, 68, 0.2)', text: '#f87171', border: 'transparent' },
  focusStyle: {},
};

function formatClock(totalSeconds) {
  const clamped = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

/**
 * The Home Now Playing card.
 *
 * Presentation adapter: the caller owns the status, offset, artwork and the
 * pause/stop intents. It renders the section heading above the shared MediaCard
 * and ticks its own clock while playing.
 */
export function PlaybackCard({ model, labels, palette, onOpenDetails, onPause, onStop, onCancel, busyAction, width = '100%' }) {
  const { width: viewportWidth } = useWindowDimensions();
  const colors = { ...fallbackPalette, ...(palette || {}) };
  const text = { ...defaultLabels, ...(labels || {}) };
  const status = model?.status || 'playing';
  const duration = Math.max(0, Number(model?.durationSeconds) || 0);
  const offset = Math.max(0, Number(model?.offsetSeconds) || 0);
  const updatedAt = Number(model?.updatedAtSeconds) || 0;
  const [now, setNow] = useState(() => Date.now());
  const playing = status === 'playing';

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [playing, updatedAt]);

  const elapsedSinceUpdate = playing && updatedAt > 0
    ? Math.max(0, Math.floor(now / 1000) - updatedAt)
    : 0;
  const stale = Boolean(playing && model?.staleAfterSeconds > 0
    && elapsedSinceUpdate > model.staleAfterSeconds);
  let current = offset + (stale ? 0 : elapsedSinceUpdate);
  if (duration > 0) current = Math.min(current, duration);
  const percent = duration > 0
    ? clampPercent((current / duration) * 100)
    : clampPercent(model?.progressPercent);
  const display = duration > 0
    ? `${formatClock(current)} / ${formatClock(duration)}`
    : formatClock(current);
  const subtitle = [model?.episodeTitle, display].filter(Boolean).join(' · ');
  const hasControl = Boolean(model?.checkin && (onPause || onStop || onCancel));
  const cardModel = {
    shape: 'landscape',
    aspectRatio: 16 / 9,
    href: model?.href || '',
    title: model?.title || '',
    image: typeof model?.image === 'string'
      ? { src: model.image, alt: model?.title || '' }
      : model?.image || { src: '', alt: model?.title || '' },
    progressBar: { percent, paused: !playing || stale },
    lines: subtitle ? [{ join: 'plain', clamp: true, parts: [{ text: subtitle }] }] : [],
  };
  const cardPalette = {
    card: colors.surface,
    text: colors.text,
    textSecondary: colors.textSecondary,
    textMuted: colors.textMuted,
    border: colors.border,
    link: colors.link,
    placeholder: colors.placeholder,
    progressTrack: colors.progressTrack,
    progressFill: colors.progressFill,
    progressPaused: colors.pausedFill,
  };
  const header = <View style={styles.headingRow}>
    <Text role="heading" aria-level={3}
      style={[styles.heading, viewportWidth < 640 && styles.headingCompact, { color: colors.text }]}>
      {text.nowPlaying}
    </Text>
    {hasControl ? <View style={styles.controls}>
      {onPause ? <Pressable accessibilityRole="button"
        accessibilityLabel={text.pauseCheckIn} accessibilityState={{ busy: busyAction === 'pause' }}
        disabled={Boolean(busyAction)} onPress={onPause}
        style={({ pressed, focused }) => [styles.controlButton, {
          backgroundColor: pressed ? colors.surfaceHover : colors.surfaceStrong,
          opacity: busyAction && busyAction !== 'pause' ? 0.5 : 1,
        }, focused && colors.focusStyle]}>
        <Text style={[styles.controlGlyph, { color: colors.text }]}>{busyAction === 'pause' ? '…' : 'Ⅱ'}</Text>
      </Pressable> : null}
      {onStop ? <Pressable accessibilityRole="button"
        accessibilityLabel={text.stopCheckIn} accessibilityState={{ busy: busyAction === 'stop' }}
        disabled={Boolean(busyAction)} onPress={onStop}
        style={({ pressed, focused }) => [styles.controlButton, {
          backgroundColor: pressed ? colors.surfaceHover : colors.surfaceStrong,
          opacity: busyAction && busyAction !== 'stop' ? 0.5 : 1,
        }, focused && colors.focusStyle]}>
        <Text style={[styles.controlGlyph, { color: colors.text }]}>{busyAction === 'stop' ? '…' : '■'}</Text>
      </Pressable> : null}
      {onCancel ? <Pressable accessibilityRole="button"
        accessibilityLabel={text.cancelCheckIn} accessibilityState={{ busy: busyAction === 'cancel' }}
        disabled={Boolean(busyAction)} onPress={onCancel}
        style={({ pressed, focused }) => [styles.controlButton, {
          backgroundColor: pressed ? colors.surfaceHover : colors.surfaceStrong,
          opacity: busyAction && busyAction !== 'cancel' ? 0.5 : 1,
        }, focused && colors.focusStyle]}>
        <Text style={[styles.controlGlyph, { color: colors.danger }]}>{busyAction === 'cancel' ? '…' : '×'}</Text>
      </Pressable> : null}
    </View> : null}
  </View>;

  return <View style={[styles.root, { width }]}>
    {header}
    <MediaCard model={cardModel} palette={cardPalette} width={width}
      readOnly onOpen={onOpenDetails ? () => onOpenDetails(model?.href) : undefined} />
  </View>;
}

function actionTone(action) {
  if (action.key === 'cancel' || action.key === 'stop') return 'ghost-danger';
  if (action.key === 'start' || action.key === 'resume' || action.key === 'finish') return 'primary';
  return 'surface';
}

/**
 * The detail page's running check-in controls and phase.
 *
 * Presentation only: the caller supplies the phase, elapsed origin and the
 * ordered action intents; the browser adapter keeps the server-owned htmx
 * controls behind it.
 */
export function CheckInState({ model, actions = [], labels, palette, onAction, busyKey }) {
  const colors = { ...fallbackPalette, ...(palette || {}) };
  const text = { ...defaultLabels, ...(labels || {}) };
  const phase = model?.phase || 'active';
  const [now, setNow] = useState(() => Date.now());
  const ticking = phase === 'active' || phase === 'session';
  const startedAt = Number(model?.startedAtSeconds) || 0;

  useEffect(() => {
    if (!ticking) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking, startedAt]);

  let elapsed = Number(model?.elapsedSeconds) || 0;
  if (ticking && startedAt > 0) {
    elapsed = Math.max(0, Math.floor(now / 1000) - startedAt);
  }
  const phaseLabel = phase === 'active'
    ? text.active
    : phase === 'finishable'
      ? text.finishable
      : phase === 'paused'
        ? text.pausedState
        : text.session;
  const code = model?.code ? ` ${model.code}` : '';

  return <View style={[styles.checkinCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.checkinHeader}>
      <Text style={[styles.checkinTitle, { color: colors.text }]}>{text.checkIn}</Text>
      {ticking ? <Text style={[styles.checkinTimer, { color: colors.textMuted }]}>
        {formatClock(elapsed)} {text.elapsed}
      </Text> : null}
    </View>
    <Text accessibilityRole="text" style={[styles.checkinPhase, { color: colors.textSecondary }]}>
      {phaseLabel}{code}
    </Text>
    {actions.length ? <View style={styles.checkinActions}>
      {actions.map(action => <Button key={action.key}
        label={action.label}
        tone={actionTone(action)}
        busy={busyKey === action.key}
        disabled={Boolean(busyKey) && busyKey !== action.key}
        palette={buttonPalette}
        onPress={() => onAction?.(action)} />)}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 8 },
  headingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  heading: { fontSize: 18, fontWeight: '600', lineHeight: 18 },
  headingCompact: { fontSize: 16, lineHeight: 21.6 },
  controls: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  controlButton: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  controlGlyph: { fontSize: 14, fontWeight: '700' },
  checkinCard: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 6 },
  checkinHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  checkinTitle: { fontSize: 14, fontWeight: '600' },
  checkinTimer: { fontSize: 12 },
  checkinPhase: { fontSize: 13 },
  checkinActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
});
