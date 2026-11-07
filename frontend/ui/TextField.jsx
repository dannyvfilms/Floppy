import React, { useMemo } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

const defaultPalette = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  danger: '#ef4444',
  disabled: '#71717a',
};

const keyboardTypes = {
  email: 'email-address',
  url: 'url',
  tel: 'phone-pad',
  number: 'number-pad',
};

/**
 * Shared labelled text/password field. The caller owns the value and receives the
 * text; `maskedPreview` is a presentation hint such as a stored-value mask, never
 * the credential itself.
 */
export function TextField({
  id,
  name,
  label,
  labelHidden = false,
  value,
  onChangeText,
  onChange,
  type = 'text',
  placeholder,
  help,
  error,
  required = false,
  disabled = false,
  maskedPreview,
  autoComplete = 'off',
  maxLength,
  accessibilityLabel,
  palette = {},
  trailing = null,
  size = 'default',
  testID,
}) {
  const colors = useMemo(() => ({ ...defaultPalette, ...palette }), [palette]);
  const large = size === 'lg';
  const secure = type === 'password';
  const change = text => {
    onChangeText?.(text);
    onChange?.({ target: { name, value: text } });
  };
  return <View style={[styles.field, large && styles.fieldLarge]} testID={testID}>
    {!labelHidden ? <View style={styles.labelRow}>
      <Text nativeID={id ? `${id}-label` : undefined} style={[styles.label, large && styles.labelLarge, { color: colors.textMuted }]}>{label}</Text>
      {maskedPreview ? <Text style={[styles.masked, { color: colors.textMuted }]}>{maskedPreview}</Text> : null}
    </View> : null}
    {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    <View style={styles.inputWrap}>
      <TextInput
        accessibilityLabel={accessibilityLabel || label}
        accessibilityHint={required ? 'Required' : undefined}
        accessibilityState={{ disabled }}
        autoCapitalize="none"
        autoComplete={autoComplete}
        autoCorrect={false}
        editable={!disabled}
        keyboardType={keyboardTypes[type] || 'default'}
        maxLength={maxLength}
        nativeID={id}
        onChangeText={change}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        secureTextEntry={secure}
        value={value ?? ''}
        style={[styles.input, large && styles.inputLarge, trailing ? styles.inputWithTrailing : null, {
          borderColor: error ? colors.danger : colors.border,
          backgroundColor: colors.inputBackground || colors.surface,
          color: colors.textSecondary,
          opacity: disabled ? 0.5 : 1,
        }]}
      />
      {trailing ? <View style={styles.trailingWrap}>{trailing}</View> : null}
    </View>
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  field: { gap: 4 },
  fieldLarge: { gap: 8 },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  label: { flexShrink: 1, fontSize: 12, fontWeight: '600' },
  labelLarge: { fontSize: 14, fontWeight: '500', lineHeight: 20 },
  masked: { flexShrink: 0, fontSize: 12, letterSpacing: 1 },
  help: { fontSize: 12, lineHeight: 17 },
  inputWrap: { position: 'relative', justifyContent: 'center' },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 9, fontSize: 14 },
  inputLarge: { borderRadius: 12, height: 50, paddingVertical: 0, paddingTop: 0, paddingBottom: 0,
    fontSize: 16, lineHeight: 24, textAlignVertical: 'center', includeFontPadding: false },
  inputWithTrailing: { paddingRight: 44 },
  trailingWrap: { position: 'absolute', right: 6, top: 0, bottom: 0, justifyContent: 'center' },
  error: { fontSize: 12, lineHeight: 17 },
});
