import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { CollectionRow, separatorStyle } from './CollectionCopies';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { systemFillColor } from './separatorColor';
import { clampValue, formatScore, isFilled } from './ratingScaleModel';

// A number row in the Tracking date picker's style: at rest one pill shows the value; pressing it opens a
// panel beneath the row. The panel is a native wheel where a platform supplies one (`renderWheel`, iOS) and
// the shared stepper elsewhere. Used for criterion values and for a criterion's minimum and maximum.
// Props only: the caller owns the value and which row is open.

export function NumberStepper({ value, min, max, step, label, onChange, palette }) {
  const number = isFilled(value) ? Number(value) : null;
  const move = direction => {
    const base = number ?? (direction > 0 ? Number(min) - step : Number(min));
    onChange(clampValue({ min, max }, base + direction * step));
  };
  const button = (direction, glyph, name) => <Pressable accessibilityRole="button"
    accessibilityLabel={`${label}: ${name}`} onPress={() => move(direction)}
    style={({ pressed }) => [styles.stepButton, { borderColor: palette.border,
      backgroundColor: pressed ? palette.surfaceMuted : palette.surface }]}>
    <Text style={[styles.glyph, { color: palette.textSecondary }]}>{glyph}</Text>
  </Pressable>;
  return <View style={styles.stepper}>
    {button(-1, '-', 'decrease')}
    <TextInput accessibilityLabel={label} keyboardType="decimal-pad" value={number === null ? '' : formatScore(number)}
      onChangeText={text => {
        if (text === '' || text === '-') { onChange(''); return; }
        const next = Number(text);
        if (Number.isFinite(next)) onChange(text.endsWith('.') ? text : String(clampValue({ min, max }, next)));
      }}
      style={[styles.input, { color: palette.text, borderColor: palette.border, backgroundColor: palette.surface }]} />
    {button(1, '+', 'increase')}
  </View>;
}

export function NumberPickerRow({
  label, icon, value, min, max, step = 1, open = false, onOpenChange, onChange, onClear,
  placeholder = 'Not set', error, palette, renderWheel, startAt,
}) {
  const filled = isFilled(value);
  const args = { value: filled ? Number(value) : Number(startAt ?? min), min: Number(min), max: Number(max), step,
    label, palette, onChange: next => onChange(String(next)) };
  const fill = systemFillColor() || palette.surfaceStrong;
  return <View>
    <CollectionRow icon={icon} label={label} palette={palette}>
      <View style={styles.pills}>
        {open && filled && onClear ? <Pressable accessibilityRole="button" accessibilityLabel={`${label}: clear`}
          onPress={() => { onClear(); onOpenChange?.(false); }}
          style={({ pressed }) => [styles.clear, { backgroundColor: fill, opacity: pressed ? 0.72 : 1 }]}>
          <Icon spec={actionIcons.x} size={14} color={palette.textMuted} />
        </Pressable> : null}
        <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${filled ? formatScore(value) : placeholder}`}
          accessibilityState={{ expanded: open }} onPress={() => onOpenChange?.(!open)}
          style={({ pressed }) => [styles.pill, { backgroundColor: fill, opacity: pressed ? 0.72 : 1 }]}>
          <Text numberOfLines={1} style={[styles.pillText, { color: filled ? palette.text : palette.textMuted }]}>
            {filled ? formatScore(value) : placeholder}</Text>
        </Pressable>
      </View>
    </CollectionRow>
    {open ? <View>
      <View style={[separatorStyle(palette), { marginLeft: icon ? 28 : 0 }]} />
      <View style={styles.panel}>{renderWheel ? renderWheel(args) : <NumberStepper {...args} />}</View>
    </View> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  pills: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1, minWidth: 0 },
  pill: { borderRadius: 17, paddingHorizontal: 12, paddingVertical: 6, minWidth: 48, alignItems: 'center' },
  pillText: { fontSize: 17 },
  clear: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  panel: { alignItems: 'center', paddingVertical: 14 },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  stepButton: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  glyph: { fontSize: 22, lineHeight: 24 },
  input: { width: 88, height: 44, borderRadius: 10, borderWidth: 1, textAlign: 'center', fontSize: 18 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
});
