import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

// Presentation only: the server supplies translated sections, lines and tones.
const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surfaceStrong: '#3f3f46',
  warning: '#f59e0b',
  monoFontFamily: 'monospace',
};

export function BackupStatus({ sections = [], palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  return <>
    {sections.map(section => <View key={section.id} style={styles.section}>
      <Text style={[styles.intro, { color: colors.text, fontFamily: colors.fontFamily }]}>
        {section.intro}
        {section.path ? <>
          {' '}<Text style={[styles.code, {
            color: colors.textSecondary,
            backgroundColor: colors.surfaceStrong,
            fontFamily: colors.monoFontFamily,
          }]}>{section.path}</Text>
        </> : null}
      </Text>
      {(section.lines || []).map((line, index) => <Text key={index}
        style={[styles.line, { color: colors[line.tone] || colors.textMuted, fontFamily: colors.fontFamily }]}>
        {line.text}
      </Text>)}
    </View>)}
  </>;
}

const styles = StyleSheet.create({
  section: { marginBottom: 20 },
  intro: { fontSize: 14, lineHeight: 21 },
  code: { fontSize: 12, lineHeight: 18, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  line: { fontSize: 12, lineHeight: 18, marginTop: 4 },
});
