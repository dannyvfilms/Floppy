import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { MarkdownNotes } from '../../../frontend/ui/MarkdownNotes';
import { MarkdownPreview } from '../../../frontend/ui/MarkdownPreview';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'NOTES',
  status: 'ported',
  title: 'Markdown notes editing and display',
  where: 'Detail notes, tracking and music track notes',
  note: 'Write/Preview, toolbar selection, safe rendering and save errors use the shared Markdown editor and native preview. The server templates and marked-based browser preview remain the web fallback.',
};

const markdownPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  link: '#818cf8',
  danger: palette.danger,
  codeBackground: palette.background,
  codeText: palette.text,
};

const labels = {
  write: 'Write',
  preview: 'Preview',
  hint: 'Markdown supported',
  heading: 'Heading',
  bold: 'Bold',
  italic: 'Italic',
  code: 'Code',
  link: 'Link',
  quote: 'Quote',
  bulletedList: 'Bulleted list',
  numberedList: 'Numbered list',
  emptyPreview: 'Nothing to preview yet.',
};

const INITIAL_NOTES = '## Second watch\n\nStill the best **quiet** ending of the season.\n\n> The relay scene earns its silence.\n\n- Watch the sound mix\n- Read the [production notes](https://example.com/notes)';

export default function NotesSlot() {
  const [value, setValue] = useState(INITIAL_NOTES);
  return <View style={[styles.root, { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <View style={styles.headingRow}>
      <Text style={[styles.heading, { color: palette.text }]}>Your notes</Text>
      <Text style={[styles.meta, { color: palette.textMuted }]}>Private · Markdown</Text>
    </View>
    <MarkdownNotes
      value={value}
      onChangeText={setValue}
      label="Notes"
      hint="Markdown supported"
      placeholder="What do you want to remember?"
      accessibilityLabel="Notes"
      labels={labels}
      palette={markdownPalette}
      Preview={MarkdownPreview} />
  </View>;
}

const styles = StyleSheet.create({
  root: { borderWidth: 1, borderRadius: radius.md, padding: spacing.lg, gap: spacing.md },
  headingRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: spacing.sm },
  heading: { fontSize: 16, fontWeight: '700' },
  meta: { fontSize: 11, fontWeight: '600' },
});
