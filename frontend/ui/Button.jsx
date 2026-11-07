import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';

const defaultTones = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'danger-deep': { background: '#b91c1c', pressed: '#991b1b', hovered: '#991b1b', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(220, 38, 38, 0.2)', hovered: 'rgba(220, 38, 38, 0.2)', text: '#f87171', border: 'transparent' },
};

export function Button({
  label,
  children,
  tone = 'primary',
  size = 'sm',
  width = 'auto',
  disabled = false,
  busy = false,
  onPress,
  accessibilityLabel,
  palette = {},
  icon,
}) {
  const content = children ?? label;
  const colors = palette[tone] || defaultTones[tone] || defaultTones.primary;
  const text = typeof content === 'string' ? content : null;
  const large = size === 'lg';
  return <Pressable
    accessibilityRole="button"
    accessibilityLabel={accessibilityLabel || text || undefined}
    accessibilityState={{ disabled, busy }}
    disabled={disabled}
    onPress={disabled ? undefined : onPress}
    style={({ pressed, hovered, focused }) => [
      styles.button,
      {
        backgroundColor: pressed ? colors.pressed : hovered ? colors.hovered : colors.background,
        borderColor: colors.border,
        borderWidth: large ? 0 : 1,
        borderRadius: palette.radius ?? 6,
        opacity: disabled ? 0.5 : 1,
        paddingVertical: large ? 12 : size === 'sm' ? 6 : 8,
        paddingHorizontal: large ? 16 : width === 'full' ? 12 : 10,
        width: width === 'full' ? '100%' : undefined,
        alignSelf: width === 'full' ? 'stretch' : 'flex-start',
      },
      focused && palette.focusStyle,
    ]}>
    <View style={styles.content}>
      {icon ? <View style={[styles.icon, { color: colors.text, fontSize: size === 'sm' ? 14 : 16 }]}>
        <Icon spec={icon} color={colors.text} />
      </View> : null}
      {text === null ? content : <Text style={[styles.label, { color: colors.text, fontSize: large ? 16 : size === 'sm' ? 13 : 14, lineHeight: large ? 24 : undefined }]}>{busy ? '…' : text}</Text>}
    </View>
  </Pressable>;
}

const styles = StyleSheet.create({
  button: { borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  content: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  icon: { alignItems: 'center', justifyContent: 'center' },
  label: { fontWeight: '600', textAlign: 'center' },
});
