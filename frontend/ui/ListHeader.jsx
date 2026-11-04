import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';

const defaultPalette = {
  text: '#fafafa',
  textMuted: '#a1a1aa',
  textSecondary: '#d4d4d8',
  border: '#3f3f46',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  disabled: '#71717a',
  overlay: 'rgba(0, 0, 0, 0.55)',
};

const defaultLabels = {
  addItem: 'Add New Item',
  more: 'More',
  exportCsv: 'Export as CSV',
  public: 'Public',
  collaborators: 'collaborators',
};

export function ListHeader({
  list,
  palette,
  labels,
  onAddItem,
  onExport,
  onMore,
  onEdit,
}) {
  const colors = { ...defaultPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  return (
    <View style={styles.header}>
      <View style={styles.titleRow}>
        <Text style={[styles.title, { color: colors.text }]}>{list.name}</Text>
      </View>
      <View style={styles.metaRow}>
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          {list.itemsCount} {list.itemsCount === 1 ? 'item' : 'items'}
        </Text>
        {list.completionPercent != null && (
          <Text style={[styles.meta, { color: colors.textMuted }]}>
            • {list.completionPercent}% complete
          </Text>
        )}
        {list.visibility === 'public' && (
          <Badge
            label={text.public}
            tone="outline"
            palette={{ outline: { borderColor: colors.border, color: colors.textSecondary } }}
          />
        )}
        {list.memberCount > 1 && (
          <Badge
            label={`${list.memberCount} ${text.collaborators}`}
            tone="outline"
            palette={{ outline: { borderColor: colors.border, color: colors.textSecondary } }}
          />
        )}
      </View>
      <View style={styles.actions}>
        {list.canEdit ? (
          <>
            <Button label={text.addItem} tone="primary" onPress={onAddItem} />
            <Button label={text.more} tone="surface" onPress={onMore} />
          </>
        ) : (
          <Button label={text.exportCsv} tone="primary" onPress={onExport} />
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { gap: 8 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 24, fontWeight: '700' },
  metaRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  meta: { fontSize: 13 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
});
