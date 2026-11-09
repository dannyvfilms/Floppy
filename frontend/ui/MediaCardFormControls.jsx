import { ModalCloseButton } from './Modal';
import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Spinner } from './Spinner';

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  radiusSmall: 6,
  fontSize: 14,
  smallFontSize: 12,
  focusStyle: {},
};

function resolvePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

export function FormHeader({ title, closeLabel, onClose, closeRef, palette }) {
  const colors = resolvePalette(palette);
  return <View style={styles.header}>
    <Text accessibilityRole="header" style={[styles.headerTitle, { color: colors.text }]}>{title}</Text>
    {onClose ? <ModalCloseButton ref={closeRef} accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose}
      style={({ focused }) => [styles.close, focused && colors.focusStyle]}>
      <Text style={[styles.closeText, { color: colors.textMuted }]}>×</Text>
    </ModalCloseButton> : null}
  </View>;
}

export function FormField({ label, required = false, error, help, children, palette }) {
  const colors = resolvePalette(palette);
  return <View style={styles.field}>
    <Text style={[styles.label, { color: colors.textSecondary }]}>
      {label}{required ? ' *' : ''}
    </Text>
    {children}
    {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
  </View>;
}

export function FormTextField({
  label,
  value,
  onChangeText,
  placeholder,
  required = false,
  error,
  help,
  multiline = false,
  keyboardType = 'default',
  editable = true,
  palette,
  accessibilityLabel,
}) {
  const colors = resolvePalette(palette);
  return <FormField label={label} required={required} error={error} help={help} palette={colors}>
    <TextInput
      accessibilityLabel={accessibilityLabel || label}
      aria-invalid={error ? true : undefined}
      editable={editable}
      keyboardType={keyboardType}
      multiline={multiline}
      numberOfLines={multiline ? 4 : 1}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={colors.textMuted}
      selectionColor={colors.accent}
      style={[
        styles.input,
        multiline && styles.textarea,
        {
          backgroundColor: colors.surfaceStrong,
          borderColor: error ? colors.danger : colors.border,
          color: colors.text,
          opacity: editable ? 1 : 0.6,
        },
      ]}
      value={value == null ? '' : String(value)}
    />
  </FormField>;
}

export function FormSelect({
  label,
  value,
  options,
  onChange,
  required = false,
  error,
  help,
  palette,
}) {
  const colors = resolvePalette(palette);
  return <FormField label={label} required={required} error={error} help={help} palette={colors}>
    <View accessibilityRole="radiogroup" style={styles.options}>
      {(options || []).map(option => {
        const selected = String(option.value) === String(value);
        return <Pressable
          key={option.value}
          accessibilityRole="radio"
          accessibilityLabel={option.label}
          accessibilityState={{ checked: selected }}
          onPress={() => onChange?.(option.value)}
          style={({ pressed, hovered }) => [
            styles.option,
            {
              backgroundColor: selected ? colors.accent : pressed || hovered ? colors.surfaceMuted : colors.surfaceStrong,
              borderColor: selected ? colors.accent : colors.border,
            },
          ]}>
          <Text style={[styles.optionText, { color: selected ? colors.accentContrast : colors.textSecondary }]}>
            {option.label}
          </Text>
        </Pressable>;
      })}
    </View>
  </FormField>;
}

export function FormStatus({ message, tone = 'muted', palette }) {
  const colors = resolvePalette(palette);
  const color = tone === 'danger' ? colors.danger : colors.textSecondary;
  return <View accessibilityLiveRegion="polite" style={styles.status}>
    {tone === 'loading' ? <Spinner size={16} color={colors.accent} /> : null}
    <Text style={[styles.statusText, { color }]}>{message}</Text>
  </View>;
}

export function FormError({ message, palette }) {
  if (!message) return null;
  const colors = resolvePalette(palette);
  return <Text accessibilityRole="alert" style={[styles.alert, { color: colors.danger, borderColor: colors.danger }]}>
    {message}
  </Text>;
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 4 },
  headerTitle: { flexShrink: 1, fontSize: 18, fontWeight: '700' },
  close: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  closeText: { fontSize: 24, lineHeight: 26 },
  field: { gap: 6 },
  label: { fontSize: 13, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  error: { fontSize: 12, lineHeight: 17, fontWeight: '600' },
  input: { minHeight: 44, borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 14 },
  textarea: { minHeight: 96, textAlignVertical: 'top' },
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: { minHeight: 36, borderWidth: 1, borderRadius: 18, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  optionText: { fontSize: 13, fontWeight: '600' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
  statusText: { flexShrink: 1, fontSize: 13, lineHeight: 19 },
  alert: { borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13, lineHeight: 19 },
});
