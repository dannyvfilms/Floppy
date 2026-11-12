import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { ProgressBar, progressFallbackPalette } from './ProgressBar';

const defaultLabels = {
  yourProgress: 'Your Progress',
  caughtUp: 'Caught Up',
  aboutProgress: 'About your progress',
  progressTip: 'Your progress is how much of the show you have watched at least once. While you rewatch, a glowing line shows how far along the rewatch is.',
  openBreakdown: 'Open the season and episode breakdown',
};

/**
 * The “Your Progress” detail card.
 *
 * Presentation only: the caller owns the value, the rewatch window, the theme
 * and what opening the breakdown means.
 */
export function ProgressCard({ model, labels, palette, onOpen }) {
  const colors = { ...progressFallbackPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  const [infoOpen, setInfoOpen] = useState(false);
  const percent = Math.max(0, Math.min(100, Number(model?.percent) || 0));
  const rewatch = model?.rewatch || null;
  const subtitle = rewatch ? rewatch.label : model?.caughtUp ? text.caughtUp : null;
  return <View style={styles.root}>
    <Pressable accessibilityRole="button"
      accessibilityLabel={`${text.yourProgress}, ${percent}%${subtitle ? `, ${subtitle}` : ''}`}
      accessibilityHint={text.openBreakdown}
      onPress={() => onOpen?.()}
      style={({ pressed, focused }) => [styles.card, {
        borderColor: colors.surfaceBorder,
        backgroundColor: pressed ? colors.surfaceHover : colors.surface,
      }, focused && colors.focusStyle]}>
      <Text style={[styles.title, { color: colors.text }]}>{text.yourProgress}
        {subtitle ? <Text style={[styles.subtitle, { color: colors.textSecondary }]}>  {subtitle}</Text> : null}
      </Text>
      <View style={styles.barRow}>
        <View style={styles.bar}>
          <ProgressBar percent={percent} rewatch={rewatch} height={8} palette={colors} label={text.yourProgress} />
        </View>
        <Text style={[styles.value, { color: colors.text }]}>{percent}%</Text>
      </View>
    </Pressable>
    <View style={styles.infoWrap}>
      <Pressable accessibilityRole="button"
        accessibilityLabel={text.aboutProgress}
        accessibilityState={{ expanded: infoOpen }}
        onPress={() => setInfoOpen(value => !value)}
        style={({ focused }) => [styles.infoButton, focused && colors.focusStyle]}>
        <Icon spec={actionIcons.info} size={14} color={colors.textMuted} />
      </Pressable>
      {infoOpen ? <View style={[styles.tip, { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceBorder }]}>
        <Text style={[styles.tipText, { color: colors.text }]}>{text.progressTip}</Text>
      </View> : null}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { position: 'relative', width: '100%' },
  card: { gap: 14, width: '100%', borderWidth: 1, borderRadius: 12, paddingHorizontal: 16, paddingVertical: 16 },
  title: { fontSize: 14, fontWeight: '600' },
  subtitle: { fontSize: 12, fontWeight: '500' },
  value: { fontSize: 20, fontWeight: '700' },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  bar: { flex: 1, minWidth: 0 },
  infoWrap: { position: 'absolute', top: 6, right: 8, alignItems: 'flex-end' },
  infoButton: { alignItems: 'center', justifyContent: 'center', width: 24, height: 24, borderRadius: 12 },
  info: { fontSize: 12, fontWeight: '700', fontStyle: 'italic' },
  tip: { marginTop: 4, width: 240, borderWidth: 1, borderRadius: 8, padding: 12 },
  tipText: { fontSize: 12, lineHeight: 17 },
});
