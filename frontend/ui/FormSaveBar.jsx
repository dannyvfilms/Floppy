import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
};

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  border: '#52525b',
  surface: '#27272a',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
};

const defaultLabels = {
  savedTitle: 'All changes saved',
  savedCopy: 'Your preferences are up to date.',
  dirtyTitle: 'Unsaved changes',
  dirtyCopy: 'Save your preferences to keep your changes.',
  savingTitle: 'Saving changes',
  savingCopy: 'Applying your preferences…',
  errorTitle: 'Could not save changes',
  save: 'Save Preferences',
  saving: 'Saving…',
};

/** Dirty/saving/error save bar with a polite status announcement. */
export function FormSaveBar({
  appearance = false,
  dirty = false,
  saving = false,
  disabled = false,
  error,
  onSave,
  saveLabel,
  labels = {},
  palette = {},
  buttonPalette = {},
}) {
  const copy = { ...defaultLabels, ...labels };
  const colors = { ...defaultPalette, ...palette };
  const title = error ? copy.errorTitle : appearance ? 'Appearance' : saving ? copy.savingTitle : dirty ? copy.dirtyTitle : copy.savedTitle;
  const description = error || (appearance ? 'Changes apply after saving.' : saving ? copy.savingCopy : dirty ? copy.dirtyCopy : copy.savedCopy);
  const dot = error ? colors.danger : dirty ? colors.warning : colors.success;
  return <View style={[styles.bar, { borderColor: colors.surfaceBorder || colors.border, backgroundColor: colors.surface }, appearance && { paddingHorizontal: 16, paddingVertical: 12.8, gap: 16, borderRadius: 8 }]}>
    <View style={styles.statusRow}>
      {!appearance ? <View accessible={false} style={[styles.dot, { backgroundColor: dot }]} /> : null}
      <View accessibilityLiveRegion="polite" aria-atomic style={styles.statusCopy}>
        <Text style={[styles.title, { color: colors.text }, appearance && { fontSize: 16, lineHeight: 24, fontWeight: '500' }]}>{title}</Text>
        <Text style={[styles.copy, { color: colors.textMuted }, appearance && { fontSize: 14, lineHeight: 20 }]}>{description}</Text>
      </View>
    </View>
    <Button
      label={saving ? copy.saving : (saveLabel || copy.save)}
      busy={saving}
      size={appearance ? 'lg' : 'sm'}
      disabled={disabled || saving}
      onPress={onSave}
      width="full"
      palette={{ ...defaultButtonPalette, ...buttonPalette }}
    >{appearance ? <Text style={{ color: buttonPalette.primary?.text || colors.text, fontSize: 16, lineHeight: 20, fontWeight: '500' }}>{saving ? copy.saving : (saveLabel || copy.save)}</Text> : undefined}</Button>
  </View>;
}

const styles = StyleSheet.create({
  bar: { gap: 12, borderWidth: 1, borderRadius: 10, padding: 12 },
  statusRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  statusCopy: { flexShrink: 1, gap: 2 },
  title: { fontSize: 13, fontWeight: '600' },
  copy: { fontSize: 12, lineHeight: 17 },
});
