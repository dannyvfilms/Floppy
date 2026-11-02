import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

/** Shared chip appearance and interaction. href/hrefAttrs are web-adapter props;
 * native consumers use onPress for navigation/actions.
 */
export function Chip({ label, palette, onPress, href, hrefAttrs, accessibilityLabel,
  accessibilityHint, hasPopup, pressed, pill = false, testID }) {
  const frame = [styles.frame, {
    borderColor: palette.badgeBorder, backgroundColor: palette.badgeBackground,
    borderRadius: pill ? 9999 : 4,
  }];
  const text = <Text style={[styles.text, { color: palette.badgeText, fontFamily: palette.fontFamily }]}>{label}</Text>;
  if (onPress || href) {
    return <Pressable role={href ? 'link' : 'button'} href={href} hrefAttrs={hrefAttrs}
      accessibilityLabel={accessibilityLabel} accessibilityHint={accessibilityHint}
      aria-haspopup={hasPopup} aria-pressed={pressed} onPress={onPress} testID={testID}
      dataSet={{ uiChip: 'true' }}
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
