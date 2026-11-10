import React from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

// The episode page's own top section, as the server template lays it out on a
// phone: a centered still, the show title, the "Season / episode / date /
// watched" line, the previous / episode picker / next row, then the track
// button with its three icon buttons. Props only: the screen adapter owns every
// request and dialog. The sections below it (synopsis, scores, genres, notes,
// cast, crew) reuse the shared detail blocks.

function Still({ src, title, palette }) {
  const [failed, setFailed] = React.useState(false);
  const uri = failed ? '' : src;
  // The web page shows a 16:9 still, or the 2:3 empty poster when there is none.
  return <View style={[styles.still, { backgroundColor: palette.placeholder, aspectRatio: uri ? 16 / 9 : 2 / 3 }]}>
    {uri ? <Image source={{ uri }} resizeMode="cover" style={StyleSheet.absoluteFill}
      accessible={false} onError={() => setFailed(true)} /> : <Text numberOfLines={3}
      style={[styles.stillPlaceholder, { color: palette.textMuted }]}>{title}</Text>}
  </View>;
}

function Separator({ palette }) {
  return <Text accessible={false} style={[styles.meta, { color: palette.textMuted }]}>{' • '}</Text>;
}

export function DetailEpisodeHeader({
  episode = {},
  selector,
  palette,
  labels = {},
  onOpenShow,
  onOpenSeason,
}) {
  const [open, setOpen] = React.useState(false);
  const picker = selector || {};
  const items = picker.items || [];
  const current = items.find(item => item.current);
  return <View style={styles.header}>
    <Still src={episode.image} title={episode.title} palette={palette} />
    <Pressable accessibilityRole="link" onPress={onOpenShow} disabled={!onOpenShow}>
      <Text accessibilityRole="header" style={[styles.title, { color: palette.text }]}>{episode.showTitle}</Text>
    </Pressable>
    <View style={styles.metaLine}>
      {episode.seasonTitle ? <Pressable accessibilityRole="link" onPress={onOpenSeason} disabled={!onOpenSeason}>
        <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.seasonTitle}</Text>
      </Pressable> : null}
      {episode.seasonTitle ? <Separator palette={palette} /> : null}
      <Pressable accessibilityRole="button" accessibilityLabel={labels.selectEpisode}
        accessibilityState={{ expanded: open }} onPress={() => setOpen(value => !value)} style={styles.metaButton}>
        <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.title}</Text>
        {episode.numberLabel ? <Separator palette={palette} /> : null}
        {episode.numberLabel ? <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.numberLabel}</Text> : null}
        <Icon spec={actionIcons.chevronDown} size={14} color={palette.textMuted} />
      </Pressable>
      {episode.airDate ? <Separator palette={palette} /> : null}
      {episode.airDate ? <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.airDate}</Text> : null}
      {episode.runtime ? <Separator palette={palette} /> : null}
      {episode.runtime ? <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.runtime}</Text> : null}
      {episode.watchedText ? <Separator palette={palette} /> : null}
      {episode.watchedText ? <Text style={[styles.meta, { color: palette.textMuted }]}>{episode.watchedText}</Text> : null}
    </View>
    {items.length ? <View style={styles.pickerRow}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.previousEpisode}
        disabled={!picker.previous} onPress={() => picker.onOpen?.(picker.previous)}
        style={[styles.step, {
          backgroundColor: picker.previous ? palette.surface : palette.surfaceMuted,
          borderColor: palette.border,
        }]}>
        <Icon spec={actionIcons.chevronLeft} size={16} color={picker.previous ? palette.text : palette.textMuted} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.selectEpisode}
        accessibilityState={{ expanded: open }} onPress={() => setOpen(value => !value)}
        style={[styles.picker, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Text numberOfLines={1} style={[styles.pickerText, { color: palette.text }]}>{current?.label || episode.title}</Text>
        <Icon spec={actionIcons.chevronDown} size={16} color={palette.text} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.nextEpisode}
        disabled={!picker.next} onPress={() => picker.onOpen?.(picker.next)}
        style={[styles.step, {
          backgroundColor: picker.next ? palette.surface : palette.surfaceMuted,
          borderColor: palette.border,
        }]}>
        <Icon spec={actionIcons.chevronRight} size={16} color={picker.next ? palette.text : palette.textMuted} />
      </Pressable>
    </View> : null}
    {open && items.length ? <View style={[styles.menu, { backgroundColor: palette.surface }]}>
      <ScrollView style={styles.menuScroll} nestedScrollEnabled>
        {items.map(item => <Pressable key={item.key} accessibilityRole="button"
          onPress={() => { setOpen(false); picker.onOpen?.(item); }}
          style={[styles.menuRow, item.current ? { backgroundColor: palette.surfaceStrong } : null]}>
          <Text numberOfLines={1} style={[styles.pickerText, { color: item.current ? palette.text : palette.textSecondary }]}>{item.label}</Text>
        </Pressable>)}
      </ScrollView>
    </View> : null}
  </View>;
}

export function DetailEpisodeActions({ track, quick = [], palette }) {
  return <View style={styles.actions}>
    {track ? <Pressable accessibilityRole="button" onPress={track.onPress} disabled={track.disabled}
      style={({ pressed }) => [styles.track, {
        backgroundColor: track.watched
          ? (pressed ? palette.accent : palette.accentStrong)
          : (pressed ? palette.surfaceStrong : palette.surfaceMuted),
        opacity: track.disabled ? 0.6 : 1,
      }]}>
      <Icon spec={actionIcons[track.watched ? 'eye' : 'eyeClosed']} size={20} color={palette.accentContrast} />
      <Text style={[styles.trackText, { color: palette.accentContrast }]}>{track.label}</Text>
    </Pressable> : null}
    {quick.length ? <View style={styles.quickRow}>
      {quick.map(item => <Pressable key={item.key} accessibilityRole="button" accessibilityLabel={item.label}
        onPress={item.onPress}
        style={({ pressed }) => [styles.quick, {
          backgroundColor: pressed ? palette.surfaceMuted : palette.surface,
          borderColor: palette.border,
        }]}>
        <Icon spec={actionIcons[item.icon]} size={16} color={palette.text} />
      </Pressable>)}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  header: { gap: 12, alignItems: 'stretch' },
  still: { alignSelf: 'center', width: 250, maxWidth: '100%', borderRadius: 8, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  stillPlaceholder: { padding: 8, fontSize: 12, lineHeight: 16, textAlign: 'center' },
  title: { fontSize: 30, lineHeight: 36, fontWeight: '700', textAlign: 'center' },
  metaLine: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center' },
  metaButton: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  meta: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  pickerRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  step: { width: 44, height: 44, borderWidth: 1, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  picker: { flex: 1, minWidth: 0, height: 44, borderWidth: 1, borderRadius: 12, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  pickerText: { fontSize: 14, fontWeight: '500', flexShrink: 1 },
  menu: { borderRadius: 6, overflow: 'hidden' },
  menuScroll: { maxHeight: 300 },
  menuRow: { paddingHorizontal: 16, paddingVertical: 12 },
  actions: { gap: 8 },
  track: { minHeight: 48, borderRadius: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12, paddingHorizontal: 20 },
  trackText: { fontSize: 16, fontWeight: '500' },
  quickRow: { flexDirection: 'row', gap: 8 },
  quick: { flex: 1, height: 44, borderWidth: 1, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
});
