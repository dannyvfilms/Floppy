import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

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
  more: 'Members',
  exportCsv: 'Export as CSV',
  menu: 'More list actions',
  public: 'Public',
  unlisted: 'Unlisted',
  smart: 'Smart',
  collaborators: 'collaborators',
  done: 'done',
};

export function ListHeader({
  list,
  palette,
  labels,
  onAddItem,
  onExport,
  onMore,
  onEdit,
  menu = null,
  trailing = null,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const colors = { ...defaultPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  const nestedList = list.isSmart || (list.source && list.source !== 'local');
  return (
    <View style={styles.header}>
      <View style={styles.titleRow}>
        <Text role="heading" aria-level={1} style={[styles.title, { color: colors.text }]}>{list.name}</Text>
      </View>
      <View style={styles.metaRow}>
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          {list.itemsCount} {list.itemsCount === 1 ? 'item' : 'items'}
        </Text>
        {list.completionPercent != null && (
          <Text style={[styles.meta, { color: colors.textMuted }]}>
            • {list.completionPercent}% {text.done}
          </Text>
        )}
        {(list.visibility === 'public' || list.visibility === 'unlisted') && (
          <Badge
            label={list.visibility === 'unlisted' ? text.unlisted : text.public}
            tone="outline"
            palette={{ outline: { borderColor: colors.border, color: colors.textSecondary } }}
          />
        )}
        {list.isSmart && (
          <Badge
            label={text.smart}
            tone="outline"
            palette={{ outline: { borderColor: colors.border, color: colors.textSecondary } }}
          />
        )}
        {list.source && list.source !== 'local' && (
          <Badge
            label={list.sourceLabel || list.source}
            tone="outline"
            palette={{ outline: { borderColor: colors.border, color: colors.textSecondary } }}
          />
        )}
        {list.role && list.role !== 'Owner' && (
          <Badge
            label={list.role}
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
        {menu && list.canEdit ? (
          <>
            <View style={styles.split}>
              {!nestedList ? <Pressable
                accessibilityRole="button"
                accessibilityLabel={text.addItem}
                onPress={onAddItem}
                style={[styles.splitMain, { backgroundColor: colors.accentStrong }]}>
                <Icon spec={actionIcons.listAdd} size={18} color={colors.accentText} />
                <Text style={[styles.splitText, { color: colors.accentText }]}>{text.addItem}</Text>
              </Pressable> : <View style={styles.splitMain} />}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={text.menu}
                accessibilityState={{ expanded: menuOpen }}
                onPress={() => setMenuOpen(open => !open)}
                style={[styles.splitCaret, { backgroundColor: colors.accentStrong, borderLeftColor: colors.accent }]}>
                <Icon spec={actionIcons.chevronDown} size={16} color={colors.accentText} />
              </Pressable>
            </View>
            {trailing}
          </>
        ) : (
          <>
            {list.canEdit ? (
              <>
                {!nestedList && (
                  <Button label={text.addItem} tone="primary" onPress={onAddItem} />
                )}
                <Button label={text.more} tone="surface" onPress={onMore} />
              </>
            ) : (
              <>
                <Button label={text.exportCsv} tone="primary" onPress={onExport} />
                <Button label={text.more} tone="surface" onPress={onMore} />
              </>
            )}
            {trailing}
          </>
        )}
      </View>
      {menu && menuOpen ? (
        <View style={[styles.menu, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          {menu.map(entry => <Pressable
            key={entry.key}
            accessibilityRole="button"
            onPress={() => {
              setMenuOpen(false);
              entry.onPress?.();
            }}
            style={styles.menuItem}>
            <Text style={[styles.menuText, { color: colors.textSecondary }]}>{entry.label}</Text>
          </Pressable>)}
        </View>
      ) : null}
      {list.description ? <Text style={[styles.description, { color: colors.textSecondary }]}>{list.description}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { gap: 8 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 24, fontWeight: '700' },
  metaRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  meta: { fontSize: 13 },
  description: { fontSize: 14, lineHeight: 20 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
  split: { flex: 1, flexDirection: 'row', borderRadius: 10, overflow: 'hidden' },
  splitMain: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 44 },
  splitText: { fontSize: 15, fontWeight: '600' },
  splitCaret: { width: 44, alignItems: 'center', justifyContent: 'center', borderLeftWidth: 1 },
  menu: { borderWidth: 1, borderRadius: 10, paddingVertical: 4 },
  menuItem: { paddingHorizontal: 14, paddingVertical: 11 },
  menuText: { fontSize: 14 },
});
