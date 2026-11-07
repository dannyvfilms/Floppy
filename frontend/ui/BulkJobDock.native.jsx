import React from 'react';
import { StyleSheet, View } from 'react-native';

export function BulkJobDock({ children, label = 'Bulk jobs', palette = {} }) {
  return <View accessibilityRole="list" accessibilityLiveRegion="polite" accessibilityLabel={label}
    style={[styles.dock, {
      backgroundColor: palette.background || '#18181b',
      borderColor: palette.border || '#3f3f46',
    }]}>
    {children}
  </View>;
}

const styles = StyleSheet.create({
  dock: { borderWidth: 1, borderRadius: 10, padding: 10, gap: 10 },
});
