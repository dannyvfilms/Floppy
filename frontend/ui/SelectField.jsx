import { actionIcons } from './actionIcons';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { DropdownMenu } from './DropdownMenu';
import { toggleDropdownSelection } from './dropdownMetrics';
import React, { useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

const defaultPalette = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  overlay: 'rgba(0, 0, 0, 0.55)',
  disabled: '#71717a',
};

// Same stroke as templates/app/icons/chevron-down.svg.
const CHEVRON_DOWN = {
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [{ tag: 'path', attrs: { d: 'm6 9 6 6 6-6' }, children: [] }],
};

const defaultLabels = {
  placeholder: 'Select an option',
  close: 'Close options',
  closeAction: 'Close',
};

/**
 * Shared preference dropdown. The caller owns the value and receives the same
 * `{ target: { name, value } }` change shape as the legacy browser control.
 */
export function SelectField({
  label,
  labelHidden = false,
  id,
  name,
  options = [],
  value,
  onChange,
  disabled = false,
  help,
  error,
  placeholder = defaultLabels.placeholder,
  accessibilityLabel,
  palette = {},
  filter = false,
  leadingIcon,
  iconChevron = false,
  testID,
  triggerStyle,
  triggerTextStyle,
  labelStyle,
  popover = false,
  multiple = false,
}) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState(null);
  const trigger = useRef(null);
  const colors = useMemo(() => ({ ...defaultPalette, ...palette }), [palette]);
  const selectedValues = multiple && Array.isArray(value) ? value : [];
  const selected = multiple ? options.filter(option => selectedValues.includes(option.value))
    : options.find(option => option.value === value);
  const selectedLabel = multiple ? selected.map(option => option.label).join(', ') : selected?.label;
  const labelId = id ? `${id}-label` : undefined;
  const triggerLabel = accessibilityLabel || `${label}: ${selectedLabel || placeholder}`;

  function choose(option) {
    if (option.disabled) return;
    const next = multiple ? toggleDropdownSelection(selectedValues, option.value) : option.value;
    onChange?.({ target: { name, value: next } });
    if (!multiple) setOpen(false);
  }

  const choices = options.map(option => {
    const active = multiple ? selectedValues.includes(option.value) : option.value === value;
    return <Pressable key={option.value} accessibilityRole={multiple ? 'checkbox' : 'radio'}
      accessibilityLabel={option.label} aria-checked={active} accessibilityState={{ checked: active, disabled: option.disabled || disabled }}
      disabled={option.disabled || disabled} onPress={() => choose(option)}
      style={({ pressed }) => [styles.option, active && { backgroundColor: colors.surfaceStrong },
        pressed && !option.disabled && { backgroundColor: colors.surfaceMuted }, option.disabled && { opacity: 0.5 }]}>
      <Text style={[styles.optionText, { color: active ? colors.text : colors.textSecondary }]}>{option.label}</Text>
      {active ? <Text style={[styles.check, { color: colors.accent }]}>✓</Text> : null}
    </Pressable>;
  });

  return <View style={styles.field} testID={testID}>
    {!labelHidden && <Text nativeID={labelId} style={[styles.label, { color: colors.textMuted }, colors.preferenceCards && { fontSize: 14, lineHeight: 19 }, labelStyle]}>{label}</Text>}
    {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    <Pressable ref={trigger}
      accessibilityRole="button"
      accessibilityLabel={triggerLabel}
      accessibilityState={{ expanded: open, disabled }}
      accessibilityHint={labelHidden ? undefined : `Opens ${label} choices`}
      disabled={disabled}
      onPress={() => {
        if (popover && trigger.current?.measureInWindow) {
          trigger.current.measureInWindow((x, y, width, height) => { setAnchor({ x, y, width, height }); setOpen(true); });
        } else { setAnchor(null); setOpen(true); }
      }}
      style={({ pressed }) => [
        styles.trigger,
        filter && styles.filterTrigger,
        {
          backgroundColor: filter ? colors.surfaceStrong : colors.surface,
          borderColor: error ? colors.danger : colors.fieldBorder || colors.border,
          opacity: disabled ? 0.5 : 1,
        },
        pressed && !disabled && { backgroundColor: filter ? colors.surfaceMuted : colors.surfaceStrong },
        triggerStyle,
      ]}>
      {filter && leadingIcon ? <View style={styles.filterIcon}>{leadingIcon}</View> : null}
      <Text numberOfLines={colors.preferenceCards ? undefined : 1} style={[styles.triggerText, { color: filter ? colors.text : colors.textSecondary }, colors.preferenceCards && { lineHeight: 20, textAlign: 'center' }, triggerTextStyle]}>{selectedLabel || placeholder}</Text>
      {filter ? <View style={styles.filterChevron}><Icon spec={CHEVRON_DOWN} color={colors.textMuted} size={16} /></View>
        : iconChevron
          ? <View style={styles.chevron}><Icon spec={actionIcons.chevronDown} color={colors.textMuted} size={16} style={{ color: colors.textMuted, fontSize: 14 }}>{'▾'}</Icon></View>
          : <Text style={[styles.chevron, { color: colors.textMuted }]}>▾</Text>}
    </Pressable>
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    {popover ? <DropdownMenu open={open} anchor={anchor} palette={colors} closeLabel={defaultLabels.close}
      estimatedHeight={Math.min(420, options.length * 40 + 8)} onClose={() => setOpen(false)}>
      <ScrollView keyboardShouldPersistTaps="handled">{choices}</ScrollView>
    </DropdownMenu> : <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.overlay}>
        <Pressable accessibilityRole="button" accessibilityLabel={defaultLabels.close} onPress={() => setOpen(false)} style={styles.backdrop} />
        <View accessibilityViewIsModal style={[styles.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.dialogHeader}>
            <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: colors.text }]}>{label}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={`${defaultLabels.closeAction}: ${label}`}
              onPress={() => setOpen(false)} style={({ pressed }) => [styles.close, pressed && { opacity: 0.7 }]}>
              <Text style={[styles.closeText, { color: colors.accent }]}>{defaultLabels.closeAction}</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.options} keyboardShouldPersistTaps="handled">
            {choices}
          </ScrollView>
        </View>
      </View>
    </Modal>}
  </View>;
}

const styles = StyleSheet.create({
  field: { gap: 4 },
  label: { fontSize: 12, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  trigger: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  filterTrigger: { minHeight: 40, paddingLeft: 16, paddingRight: 40, borderRadius: 6 },
  filterIcon: { width: 16, height: 16, alignItems: 'center', justifyContent: 'center' },
  filterChevron: { position: 'absolute', right: 12 },
  triggerText: { flexShrink: 1, fontSize: 14 },
  chevron: { fontSize: 14 },
  error: { fontSize: 12, lineHeight: 17 },
  overlay: { flex: 1, justifyContent: 'center', padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0, 0, 0, 0.55)' },
  dialog: { width: '100%', maxWidth: 300, alignSelf: 'center', maxHeight: '80%',
    borderWidth: 1, borderRadius: 12, paddingVertical: 8 },
  dialogHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingBottom: 8 },
  dialogTitle: { flexShrink: 1, fontSize: 16, fontWeight: '600' },
  close: { paddingVertical: 4, paddingHorizontal: 4 },
  closeText: { fontSize: 13, fontWeight: '600' },
  options: { maxHeight: 420 },
  option: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingVertical: 11 },
  optionText: { flexShrink: 1, fontSize: 14 },
  check: { fontSize: 14, fontWeight: '700' },
});
