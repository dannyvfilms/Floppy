import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { palette, spacing } from '../theme';

const TABS = [
  { id: 'home', label: 'Home' },
  { id: 'discover', label: 'Discover' },
  { id: 'library', label: 'Library' },
  { id: 'calendar', label: 'Calendar' },
  { id: 'settings', label: 'Settings' },
];

export function TabBar({ active, onChange }) {
  return <View style={styles.bar} accessibilityRole="tablist">
    {TABS.map(tab => {
      const selected = active === tab.id;
      return <Pressable key={tab.id} accessibilityRole="tab" accessibilityState={{ selected }}
        accessibilityLabel={tab.label} onPress={() => onChange(tab.id)}
        style={({ pressed }) => [styles.tab, pressed && styles.pressed]}>
        <View style={[styles.dot, selected && styles.dotActive]} />
        <Text style={[styles.label, selected && styles.labelActive]}>{tab.label}</Text>
      </Pressable>;
    })}
  </View>;
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: palette.border, backgroundColor: palette.background, paddingTop: 6, paddingBottom: 8 },
  tab: { flex: 1, alignItems: 'center', gap: 4, paddingVertical: 4 },
  pressed: { opacity: 0.7 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: 'transparent' },
  dotActive: { backgroundColor: palette.accent },
  label: { color: palette.textMuted, fontSize: 11, fontWeight: '500' },
  labelActive: { color: palette.text },
});
