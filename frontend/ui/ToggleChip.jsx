import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

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
  accentStrong: '#4f46e5',
  surfaceMuted: '#52525b',
};

/** Controlled two-state preference control with a stable accessible name. A palette
 * that supplies `thumb` (native settings) draws the switch the web uses; without
 * it the chip form is kept for the browser islands. */
export function ToggleChip({
  checkbox = false,
  icon,
  labelHidden = false,
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
  if (checkbox) return <Pressable accessibilityRole="checkbox" accessibilityLabel={label}
    aria-checked={Boolean(value)}
    accessibilityState={{ disabled, checked: Boolean(value) }} disabled={disabled}
    onPress={() => onChange(!value)} style={[styles.field, { justifyContent: 'flex-start', flex: 1 }, disabled && styles.disabled]}>
    <View style={{ width: 16, height: 16, borderRadius: 4, borderWidth: 1, borderColor: colors.surfaceBorder || colors.border,
      backgroundColor: value ? colors.accent : colors.surface, alignItems: 'center', justifyContent: 'center' }}>
      {value ? <Icon spec={actionIcons.check} color={colors.accentText || colors.text} size={12} /> : null}
    </View>
    <View style={{ flex: 1, gap: 2 }}>
      <Text style={{ color: colors.textSecondary || colors.text, fontFamily: colors.fontFamily, fontSize: 14, flexShrink: 1 }}>{label}</Text>
      {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    </View>
  </Pressable>;
  return <View style={[styles.field, disabled && styles.disabled]}>
    {!labelHidden ? <View style={styles.copy}>
      {label ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        {icon ? <Icon spec={icon} color={colors.link || colors.accent} size={16} /> : null}
        <Text style={[styles.label, { color: colors.text }, colors.pageCards && { fontSize: 14, lineHeight: 20, fontWeight: '500', flexShrink: 1 }]}>{label}</Text>
      </View> : null}
      {help ? <Text style={[styles.help, { color: colors.textMuted }, icon && { marginLeft: 24 }, colors.pageCards && { lineHeight: 16 }]}>{help}</Text> : null}
    </View> : null}
    {colors.thumb ? <Pressable
      accessibilityRole="switch"
      accessibilityLabel={label || `${offLabel} / ${onLabel}`}
      accessibilityHint={disabled ? undefined : `Turns ${label || text} ${value ? 'off' : 'on'}`}
      accessibilityState={{ disabled, checked: Boolean(value) }}
      aria-checked={Boolean(value)}
      disabled={disabled}
      onPress={disabled ? undefined : () => onChange(!value)}
      testID={`toggle-${label || 'preference'}`}
      style={[styles.track, { backgroundColor: value ? colors.accentStrong : colors.surfaceMuted }, colors.pageCards && { width: 36, height: 20, borderRadius: 10, padding: 1 }]}>
      <View style={[styles.thumb, { backgroundColor: colors.thumb }, colors.pageCards && { width: 18, height: 18, borderRadius: 9 }, value && styles.thumbOn]} />
    </Pressable> : <Chip
      label={text}
      palette={colors}
      pressed={value}
      accessibilityLabel={label || `${offLabel} / ${onLabel}`}
      accessibilityHint={disabled ? undefined : `Turns ${label || text} ${value ? 'off' : 'on'}`}
      accessibilityState={{ disabled, selected: value }}
      onPress={disabled ? undefined : () => onChange(!value)}
      testID={`toggle-${label || 'preference'}`}
    />}
  </View>;
}

const styles = StyleSheet.create({
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  disabled: { opacity: 0.5 },
  copy: { flexShrink: 1, gap: 2 },
  label: { fontSize: 13, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  track: { width: 44, height: 24, borderRadius: 12, padding: 2, justifyContent: 'center', flexShrink: 0 },
  thumb: { width: 20, height: 20, borderRadius: 10 },
  thumbOn: { alignSelf: 'flex-end' },
});
