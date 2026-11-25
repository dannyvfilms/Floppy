import React from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';
import { Icon } from './Icon';

/**
 * A round icon-only button: Now Playing's Pause, Stop and Cancel today, any
 * small round control tomorrow.
 *
 * Presentation only. The caller owns the intent, the busy state and the colours
 * (`palette.surface`, `surfaceHover`, `text`, `danger`, `focusStyle`).
 */
export function IconButton({ icon, label, tone = 'default', busy = false, disabled = false, dimmed = false, size = 32, palette = {}, onPress }) {
  const color = tone === 'danger' ? palette.danger : palette.text;
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{ busy, disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed, hovered, focused }) => [
      styles.button,
      { width: size, height: size, borderRadius: size / 2,
        backgroundColor: pressed || hovered ? palette.surfaceHover : palette.surface,
        opacity: dimmed ? 0.5 : 1 },
      focused && palette.focusStyle,
    ]}>
    {busy
      ? <Text accessible={false} style={[styles.busy, { color }]}>…</Text>
      : <Icon spec={icon} color={color} size={16} style={[styles.glyph, { color }]} />}
  </Pressable>;
}

const styles = StyleSheet.create({
  button: { alignItems: 'center', justifyContent: 'center' },
  busy: { fontSize: 14, fontWeight: '700' },
  glyph: { fontSize: 14, fontWeight: '700' },
});
