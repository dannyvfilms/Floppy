import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

// Collection entries and calendar releases share the same row rhythm.
export function CardRow({ leading, children, trailing, onPress, accessibilityLabel, first = false }) {
  const content = <>
    {leading || null}
    <View style={styles.body}>{children}</View>
    {trailing || null}
  </>;
  return onPress ? <Pressable accessibilityRole="link" accessibilityLabel={accessibilityLabel}
    onPress={onPress} style={({ pressed }) => [styles.row, first && styles.first, pressed && styles.pressed]}>{content}</Pressable>
    : <View style={[styles.row, first && styles.first]}>{content}</View>;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 8 },
  first: { paddingTop: 16 },
  body: { flex: 1, minWidth: 0, gap: 3 },
  pressed: { opacity: 0.72 },
});
