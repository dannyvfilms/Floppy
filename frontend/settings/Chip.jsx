import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

/** Shared chip appearance and interaction. Native consumers use onPress for an
 * action; a web adapter attaches browser link props to the link mode.
 */
export function Chip({ label, palette, onPress, link = false, accessibilityRole,
  accessibilityLabel, accessibilityHint, hasPopup, pressed, pill = false,
  testID, ...platformProps }) {
  const frame = [styles.frame, {
    borderColor: palette.badgeBorder, backgroundColor: palette.badgeBackground,
    borderRadius: pill ? 9999 : 4,
  }];
  const text = <Text style={[styles.text, { color: palette.badgeText, fontFamily: palette.fontFamily }]}>{label}</Text>;
  if (onPress || link) {
    return <Pressable accessibilityRole={accessibilityRole || (link ? 'link' : 'button')}
      accessibilityLabel={accessibilityLabel} accessibilityHint={accessibilityHint}
      aria-haspopup={hasPopup} aria-pressed={pressed}
      accessibilityState={pressed === undefined ? undefined : { selected: pressed }}
      onPress={onPress} testID={testID} {...platformProps}
      style={({ focused, hovered }) => [frame, palette.interactiveStyle,
        focused && palette.focusStyle, hovered && { backgroundColor: palette.badgeHover }]}>
      {text}
    </Pressable>;
  }
  return <View style={frame} testID={testID}>{text}</View>;
}

const styles = StyleSheet.create({
  frame: { borderWidth: 1, borderStyle: 'solid', paddingHorizontal: 8, paddingVertical: 4,
    flexShrink: 0, maxWidth: '100%' },
  text: { fontSize: 12, lineHeight: 16, textDecorationLine: 'none' },
});
