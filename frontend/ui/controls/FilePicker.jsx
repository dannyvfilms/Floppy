import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

const defaultPalette = {
  background: '#3f3f46',
  pressed: '#52525b',
  hovered: '#52525b',
  text: '#fafafa',
  border: '#52525b',
  radius: 8,
};

function filesFrom(value) {
  if (!value || value.canceled) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.files)) return value.files;
  return [value];
}

/**
 * Shared picker presentation and native adapter seam. The universal component
 * never opens a browser input: native code supplies `pickFiles({ accept,
 * multiple })`, which resolves to an array of file-like objects (or
 * `{ files }`), and receives the same `event.target.files` shape as the web
 * implementation through `onChange`.
 */
export function FilePicker({
  label,
  onChange,
  accept,
  multiple = false,
  disabled = false,
  palette = {},
  pickFiles,
  onError,
  testID,
}) {
  const colors = { ...defaultPalette, ...palette };
  const [busy, setBusy] = useState(false);
  const unavailable = disabled || typeof pickFiles !== 'function';
  const hint = `${multiple ? 'Choose one or more files' : 'Choose a file'}${accept ? `. Accepted types: ${accept}` : ''}`;

  async function choose() {
    if (unavailable || busy) return;
    setBusy(true);
    try {
      const files = filesFrom(await pickFiles({ accept, multiple }));
      const selected = multiple ? files : files.slice(0, 1);
      if (selected.length) {
        onChange?.({ target: { files: selected }, source: 'native', accept, multiple });
      }
    } catch (error) {
      onError?.(error);
    } finally {
      setBusy(false);
    }
  }

  return <View style={styles.field} testID={testID}>
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: unavailable, busy }}
      disabled={unavailable}
      onPress={choose}
      style={({ pressed, hovered, focused }) => [
        styles.picker,
        {
          backgroundColor: pressed ? colors.pressed : hovered ? colors.hovered : colors.background,
          borderColor: colors.border,
          borderRadius: colors.radius ?? 8,
          opacity: unavailable ? 0.5 : 1,
        },
        focused && palette.focusStyle,
      ]}>
      <Text style={[styles.label, { color: colors.text }]}>{busy ? '…' : label}</Text>
    </Pressable>
  </View>;
}

const styles = StyleSheet.create({
  field: { alignSelf: 'flex-start', gap: 4 },
  picker: { alignSelf: 'flex-start', alignItems: 'center', justifyContent: 'center', borderWidth: 1, paddingHorizontal: 12, paddingVertical: 7 },
  label: { fontSize: 13, fontWeight: '600' },
});
