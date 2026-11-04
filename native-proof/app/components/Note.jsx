import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { palette, radius, spacing } from '../theme';

export function Note({ surface, children, compact = false }) {
  return <View style={[styles.note, compact && styles.compact]}>
    <View style={styles.row}>
      <Text style={styles.id}>{surface.id}</Text>
      <Text style={styles.status}>{surface.status === 'ported' ? 'Ported' : surface.status === 'in_progress' ? 'In progress' : 'Not ported yet'}</Text>
    </View>
    <Text style={styles.title}>{surface.title}</Text>
    <Text style={styles.where}>{surface.where}</Text>
    {surface.note ? <Text style={styles.copy}>{surface.note}</Text> : null}
    {children}
  </View>;
}

const styles = StyleSheet.create({
  note: {
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: palette.surfaceMuted,
    borderRadius: radius.md,
    backgroundColor: palette.surface,
    padding: spacing.md,
    gap: spacing.sm,
  },
  compact: { paddingVertical: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  id: { color: palette.accent, fontSize: 11, fontWeight: '700', letterSpacing: 0.8 },
  status: { color: palette.textMuted, fontSize: 11 },
  title: { color: palette.text, fontSize: 15, fontWeight: '600' },
  where: { color: palette.textSecondary, fontSize: 12 },
  copy: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
