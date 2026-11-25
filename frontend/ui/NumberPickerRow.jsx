import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { CollectionRow, separatorStyle } from './CollectionCopies';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { systemFillColor } from './separatorColor';
import { clampValue, formatScore, isFilled } from './ratingScaleModel';

// A number row in the Tracking date picker's style: at rest one pill shows the value; pressing it opens a
// panel beneath the row. The panel is a native wheel where a platform supplies one (`renderWheel`, iOS) and
// the shared stepper elsewhere. Desktop web has no pills: the row holds a plain number input, like the old
// score field (`inline`). Props only: the caller owns the value and which row is open.

/** A plain number input. Whole numbers unless `decimal`; an empty field means no value. */
export function NumberInput({ value, min, max, decimal = false, label, onChange, palette, width = 72, align = 'right' }) {
  const text = isFilled(value) ? String(value) : '';
  return <TextInput accessibilityLabel={label} keyboardType={decimal ? 'decimal-pad' : 'number-pad'}
    inputMode={decimal ? 'decimal' : 'numeric'} value={text} selectionColor={palette.accent}
    onChangeText={next => {
      const cleaned = next.replace(decimal ? /[^0-9.-]/g : /[^0-9-]/g, '');
      if (cleaned === '' || cleaned === '-') { onChange(''); return; }
      if (/\.$/.test(cleaned)) { onChange(cleaned); return; }
      const number = Number(cleaned);
      if (Number.isFinite(number)) onChange(String(clampValue({ min, max }, number)));
    }}
    style={[styles.numberInput, { width, textAlign: align, color: palette.text,
      borderColor: palette.inputBorder || palette.border, backgroundColor: palette.surfaceStrong || palette.surface }]} />;
}

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
    <NumberInput value={number === null ? '' : formatScore(number)} min={min} max={max} decimal label={label}
      onChange={next => onChange(next)} palette={palette} width={88} align="center" />
    {button(1, '+', 'increase')}
  </View>;
}

export function NumberPickerRow({
  label, icon, value, min, max, step = 1, open = false, onOpenChange, onChange, onClear,
  placeholder = 'Not set', error, palette, renderWheel, startAt, inline = false, decimal = false, display,
}) {
  const filled = isFilled(value);
  const shown = display ?? (filled ? formatScore(value) : '');
  // A wheel only lists steps, so the value it opens on is the nearest one.
  const snap = number => Math.min(Number(max), Math.max(Number(min), Math.round((number - Number(min)) / step) * step + Number(min)));
  const args = { value: snap(filled ? Number(value) : Number(startAt ?? min)), min: Number(min), max: Number(max), step,
    label, palette, onChange: next => onChange(String(next)) };
  const fill = systemFillColor() || palette.surfaceStrong;
  if (inline) {
    return <View>
      <CollectionRow icon={icon} label={label} palette={palette}>
        <NumberInput value={shown} min={min} max={max} decimal={decimal} label={label} palette={palette}
          onChange={next => (next === '' && onClear ? onClear() : onChange(next))} />
      </CollectionRow>
      {error ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
    </View>;
  }
  return <View>
    <CollectionRow icon={icon} label={label} palette={palette}>
      <View style={styles.pills}>
        {open && filled && onClear ? <Pressable accessibilityRole="button" accessibilityLabel={`${label}: clear`}
          onPress={() => { onClear(); onOpenChange?.(false); }}
          style={({ pressed }) => [styles.clear, { backgroundColor: fill, opacity: pressed ? 0.72 : 1 }]}>
          <Icon spec={actionIcons.x} size={14} color={palette.textMuted} />
        </Pressable> : null}
        <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${shown || placeholder}`}
          accessibilityState={{ expanded: open }} onPress={() => onOpenChange?.(!open)}
          style={({ pressed }) => [styles.pill, { backgroundColor: fill, opacity: pressed ? 0.72 : 1 }]}>
          <Text numberOfLines={1} style={[styles.pillText, { color: shown ? palette.text : palette.textMuted }]}>
            {shown || placeholder}</Text>
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
  numberInput: { height: 36, borderRadius: 6, borderWidth: 1, paddingHorizontal: 10, fontSize: 15 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
});
