import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'NOTES',
  status: 'in_progress',
  title: 'Markdown notes editing and display',
  where: 'Detail notes, tracking and music track notes',
  note: 'Write/Preview, toolbar selection, safe rendering and save errors are being ported to the shared Markdown editor and preview. The server templates and marked adapter remain the web fallback until the port lands.',
};

export default function NotesSlot() {
  return <View style={[styles.root, { borderColor: palette.border }]}>
    <Text style={[styles.copy, { color: palette.textMuted }]}>Markdown notes port in progress.</Text>
  </View>;
}

const styles = StyleSheet.create({
  root: { borderWidth: 1, borderRadius: 10, padding: spacing.md },
  copy: { fontSize: 13 },
});
