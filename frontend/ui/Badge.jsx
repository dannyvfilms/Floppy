import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

// Presentation receives concrete tokens and an optional platform navigation action.
export function Badge({ label, size = 'sm', tone = 'outline', palette = {}, appearance, nowrap = false, onPress, accessibilityLabel }) {
  const [textWidth, setTextWidth] = useState(null);
  const appearanceStyle = [styles.badge, styles[size] || styles.sm, palette[tone], appearance];
  const flat = StyleSheet.flatten(appearanceStyle);
  const horizontalPadding = (flat.paddingLeft ?? flat.paddingHorizontal ?? flat.padding ?? 0) + (flat.paddingRight ?? flat.paddingHorizontal ?? flat.padding ?? 0);
  const width = textWidth === null ? undefined : Math.ceil(textWidth + horizontalPadding + (flat.borderWidth || 0) * 2);
  const text = <Text accessible={onPress ? false : undefined} accessibilityLabel={onPress ? undefined : accessibilityLabel}
    numberOfLines={nowrap ? 1 : undefined}
    style={[appearanceStyle, nowrap && styles.nowrap, width !== undefined && { width }]}>{label}</Text>;
  const content = nowrap ? <View style={styles.nowrapContainer}>
    <Text accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      onTextLayout={event => setTextWidth(event.nativeEvent.lines[0]?.width ?? 0)}
      style={[appearanceStyle, styles.measure]}>{label}</Text>
    {text}
  </View> : text;
  return onPress ? <Pressable accessibilityRole="link" accessibilityLabel={accessibilityLabel || label}
    onPress={onPress} style={styles.link}>{content}</Pressable> : content;
}

const styles = StyleSheet.create({
  badge: { borderRadius: 9999, overflow: 'hidden' },
  xs: { fontSize: 11, paddingVertical: 4, paddingHorizontal: 8 },
  sm: { fontSize: 12, lineHeight: 16, paddingVertical: 2, paddingHorizontal: 8 },
  md: { fontSize: 14, lineHeight: 20, paddingVertical: 4, paddingHorizontal: 12 },
  tag: { fontSize: 12, lineHeight: 16, height: 24, paddingHorizontal: 10 },
  nowrap: { flexShrink: 0 },
  nowrapContainer: { flexDirection: 'row', alignSelf: 'flex-start', flexShrink: 0 },
  measure: { position: 'absolute', left: -10000, width: 10000, opacity: 0 },
  link: { alignSelf: 'flex-start', flexShrink: 0 },
});
