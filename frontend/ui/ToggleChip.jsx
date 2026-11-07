import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';

const defaultPalette = {
  text: '#fafafa',
  textMuted: '#a1a1aa',
  border: '#52525b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
};

/** Controlled two-state preference chip with a stable accessible name. */
export function ToggleChip({
  value,
  onChange,
  offLabel,
  onLabel,
  label,
  help,
  disabled = false,
  palette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const text = value ? onLabel : offLabel;
  return <View style={[styles.field, disabled && styles.disabled]}>
    <View style={styles.copy}>
      {label ? <Text style={[styles.label, { color: colors.text }]}>{label}</Text> : null}
      {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    </View>
    <Chip
      label={text}
      palette={colors}
      pressed={value}
      accessibilityLabel={label || `${offLabel} / ${onLabel}`}
      accessibilityHint={disabled ? undefined : `Turns ${label || text} ${value ? 'off' : 'on'}`}
      accessibilityState={{ disabled, selected: value }}
      onPress={disabled ? undefined : () => onChange(!value)}
      testID={`toggle-${label || 'preference'}`}
    />
  </View>;
}

const styles = StyleSheet.create({
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  disabled: { opacity: 0.5 },
  copy: { flexShrink: 1, gap: 2 },
  label: { fontSize: 13, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
});
