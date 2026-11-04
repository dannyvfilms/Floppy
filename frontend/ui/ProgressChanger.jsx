import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Spinner } from './Spinner';

// Presentation only: the adapter owns the write, its busy state and the theme.
export function ProgressChanger({
  value,
  max = null,
  unit = '',
  showMax = false,
  canDecrease = true,
  canIncrease = true,
  busyOperation = null,
  flashOperation = null,
  decreaseLabel,
  increaseLabel,
  onAdjust,
  palette,
}) {
  const showButtons = palette.showButtons !== false;
  const text = `${value}${showMax && max !== null ? ` / ${max}` : ''}${unit ? ` ${unit}` : ''}`;
  function AdjustButton({ operation, label, enabled }) {
    const busy = busyOperation === operation;
    const color = enabled ? palette.icon : palette.disabledIcon;
    return <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !enabled, busy }}
      disabled={!enabled}
      onPress={() => onAdjust?.(operation)}
      style={({ pressed, focused, hovered }) => [
        styles.button,
        {
          width: palette.buttonSize,
          height: palette.buttonSize,
          borderRadius: palette.radius,
          backgroundColor: flashOperation === operation ? palette.flash : pressed || hovered ? palette.buttonHover : palette.button,
          opacity: enabled ? 1 : 0.5,
        },
        focused && palette.focusStyle,
      ]}>
      {busy
        ? <Spinner size={palette.iconSize} color={color} />
        : <AdjustIcon operation={operation} color={color} size={palette.iconSize} />}
    </Pressable>;
  }
  return <View style={[styles.row, palette.showButtons === false && styles.textOnly]}>
    {showButtons && <AdjustButton operation="decrease" label={decreaseLabel} enabled={canDecrease} />}
    <View accessibilityLiveRegion="polite" aria-atomic
      style={[styles.valueWrap, { minWidth: palette.minWidth }]}>
      <Text numberOfLines={1} style={[styles.value, { color: palette.text, fontSize: palette.fontSize }]}>{text}</Text>
    </View>
    {showButtons && <AdjustButton operation="increase" label={increaseLabel} enabled={canIncrease} />}
  </View>;
}

function AdjustIcon({ operation, color, size }) {
  const bar = Math.max(2, Math.round(size / 6));
  return <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
    <View style={{ position: 'absolute', width: size, height: bar, borderRadius: bar / 2, backgroundColor: color }} />
    {operation === 'increase' && <View style={{ position: 'absolute', width: bar, height: size, borderRadius: bar / 2, backgroundColor: color }} />}
  </View>;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 16 },
  textOnly: { width: '100%' },
  button: { alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  valueWrap: { alignItems: 'center', justifyContent: 'center' },
  value: { fontWeight: '500', textAlign: 'center' },
});
