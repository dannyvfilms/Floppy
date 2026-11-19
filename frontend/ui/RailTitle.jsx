import React from 'react';
import { StyleSheet, Text } from 'react-native';

/**
 * The heading every Home row and shelf uses: 18px, 16px on phones.
 * Rail draws its row titles with it; Now Playing uses it for its own heading.
 */
export function RailTitle({ children, color, compact = false, style }) {
  return <Text role="heading" aria-level={3} numberOfLines={1}
    style={[styles.title, compact && styles.compact, { color }, style]}>{children}</Text>;
}

const styles = StyleSheet.create({
  title: { fontSize: 18, fontWeight: '600', lineHeight: 18, flexShrink: 0.2, minWidth: 0 },
  compact: { fontSize: 16, lineHeight: 21.6 },
});
