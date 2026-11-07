import React, { useEffect, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../ui/Button';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  danger: '#ef4444',
  warning: '#f59e0b',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: 10,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

export function ConfirmDialog({
  visible = false,
  title = 'Are you sure?',
  message,
  warning,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  requirePhrase,
  phraseLabel,
  phrasePlaceholder,
  busy = false,
  error,
  palette = {},
  buttonPalette = {},
  onCancel,
  onConfirm,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const [phrase, setPhrase] = useState('');

  useEffect(() => {
    if (!visible) setPhrase('');
  }, [visible]);

  const ready = !requirePhrase || phrase === requirePhrase;

  return <Modal transparent visible={visible} animationType="fade" accessibilityViewIsModal onRequestClose={() => { if (!busy) onCancel?.(); }}>
    <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
      <View style={[styles.dialog, { backgroundColor: colors.surface, borderColor: colors.border, borderRadius: colors.radius }]}>
        <Text role="heading" aria-level={2} style={[styles.title, { color: colors.text }]}>{title}</Text>
        {message ? <Text style={[styles.copy, { color: colors.textSecondary }]}>{message}</Text> : null}
        {warning ? <Text style={[styles.warning, { color: colors.warning }]}>{warning}</Text> : null}
        {requirePhrase ? <View style={styles.field}>
          <Text style={[styles.label, { color: colors.textMuted }]}>{phraseLabel || `Type ${requirePhrase} to confirm.`}</Text>
          <TextInput
            accessibilityLabel={phraseLabel || `Type ${requirePhrase} to confirm`}
            autoCapitalize="characters"
            autoCorrect={false}
            editable={!busy}
            onChangeText={setPhrase}
            placeholder={phrasePlaceholder || requirePhrase}
            placeholderTextColor={colors.textMuted}
            value={phrase}
            style={[styles.input, { backgroundColor: colors.surfaceStrong, borderColor: colors.border, color: colors.text }]}
          />
        </View> : null}
        {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
        <View style={styles.actions}>
          <Button label={cancelLabel} tone="surface" disabled={busy} onPress={onCancel} palette={buttons} />
          <Button label={confirmLabel} tone="danger-solid" busy={busy} disabled={!ready} onPress={onConfirm} palette={buttons} />
        </View>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1, justifyContent: 'center', padding: 16 },
  dialog: { borderWidth: 1, padding: 18, gap: 12, maxWidth: 440, width: '100%', alignSelf: 'center' },
  title: { fontSize: 17, fontWeight: '700' },
  copy: { fontSize: 13, lineHeight: 19 },
  warning: { fontSize: 13, lineHeight: 19, fontWeight: '600' },
  field: { gap: 4 },
  label: { fontSize: 12, fontWeight: '600' },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 9, fontSize: 14 },
  error: { fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 },
});
