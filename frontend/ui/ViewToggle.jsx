import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

// The web's list layout switch: one icon per layout, the active one filled
// with the accent colour. Options are { value, label, icon } where icon is an
// actionIcons key; the owner decides which layouts exist.
export function ViewToggle({ options = [], value, palette = {}, onChange }) {
  const accent = palette.accentStrong || palette.accent;
  const track = palette.surfaceStrong || palette.surface;
  const active = palette.accentText || palette.text;
  const idle = palette.textSecondary || palette.text;
  return <View accessibilityRole="radiogroup" style={[styles.group, { backgroundColor: track }]}>
    {options.map(option => {
      const selected = option.value === value;
      return <Pressable
        key={option.value}
        accessibilityRole="radio"
        accessibilityLabel={option.label}
        accessibilityState={{ selected }}
        onPress={() => onChange?.(option.value)}
        style={[styles.item, selected && { backgroundColor: accent }]}>
        <Icon spec={actionIcons[option.icon]} size={18} color={selected ? active : idle} />
      </Pressable>;
    })}
  </View>;
}

const styles = StyleSheet.create({
  group: { flexDirection: 'row', alignItems: 'center', borderRadius: 8, overflow: 'hidden' },
  item: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
});
