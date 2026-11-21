import React from 'react';
import { StyleSheet, Text } from 'react-native';

// One title for every sheet, dialog, form bar and page. Role decides the size:
// compact pickers 16, dialogs 18, sheets 20, form bars 24 (all 600), and bold headings 24 and page titles 28 (700).
const SIZES = {
  compact: { fontSize: 16, fontWeight: '600' },
  dialog: { fontSize: 18, fontWeight: '600' },
  sheet: { fontSize: 20, fontWeight: '600' },
  bar: { fontSize: 24, fontWeight: '600' },
  heading: { fontSize: 24, fontWeight: '700' },
  page: { fontSize: 28, fontWeight: '700' },
};

/**
 * The title every sheet, dialog and page draws. Presentation only: the caller owns the
 * colour, layout (`style`) and close control.
 */
export function Title({ children, color, size = 'dialog', level = 2, numberOfLines, style }) {
  return <Text role="heading" aria-level={level} numberOfLines={numberOfLines}
    style={[styles.title, SIZES[size], color ? { color } : null, style]}>{children}</Text>;
}

const styles = StyleSheet.create({ title: { fontWeight: '600' } });
