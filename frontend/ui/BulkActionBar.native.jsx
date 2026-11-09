import { Modal } from './Modal';
import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  overlay: 'rgba(0, 0, 0, 0.55)',
};

const glyphs = {
  status: '✓',
  list: '☰',
  collection: '▣',
  tag: '#',
  more: '⋯',
  check: '✓',
  close: '×',
};

export function BulkActionBar({ count, actions = [], disabled = false, deselectDisabled = false, onDeselect, palette = {} }) {
  const [open, setOpen] = useState(null);
  const colors = useMemo(() => ({ ...FALLBACK_PALETTE, ...palette }), [palette]);
  const menu = open && actions.find(action => action.key === open);
  const close = () => setOpen(null);
  const choose = handler => { close(); handler(); };

  return <View accessibilityRole="toolbar" accessibilityLabel="Bulk actions"
    style={[styles.bar, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
    <View style={styles.count}>
      <Text style={[styles.check, { color: colors.accent }]}>{glyphs.check}</Text>
      <Text style={[styles.countText, { color: colors.textSecondary }]}>
        <Text style={{ color: colors.text, fontWeight: '700' }}>{count.toLocaleString()}</Text>
        {` ${count === 1 ? 'item' : 'items'} selected`}
      </Text>
    </View>
    <View style={styles.actions}>
      {actions.map(action => <Pressable key={action.key} accessibilityRole="button"
        accessibilityLabel={action.label} disabled={disabled}
        onPress={() => { if (action.items) setOpen(action.key); else action.onSelect?.(); }}
        style={({ pressed }) => [styles.action,
          { borderColor: colors.border, backgroundColor: pressed && !disabled ? colors.surfaceMuted : colors.surface },
          disabled && styles.disabled]}>
        <Text style={[styles.glyph, { color: colors.textSecondary }]}>{glyphs[action.icon]}</Text>
      </Pressable>)}
    </View>
    <Pressable accessibilityRole="button" accessibilityLabel="Deselect All" disabled={deselectDisabled}
      onPress={onDeselect} style={({ pressed }) => [styles.deselect, pressed && !deselectDisabled && styles.pressed]}>
      <Text style={[styles.deselectText, { color: colors.textSecondary }]}>{glyphs.close} Deselect All</Text>
    </Pressable>
    <Modal transparent visible={!!menu} animationType="fade" onRequestClose={close}>
      <View style={styles.overlay}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close actions" onPress={close} style={styles.backdrop} />
        <View style={[styles.sheet, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={[styles.sheetTitle, { color: colors.text }]}>{menu?.label}</Text>
          <ScrollView style={styles.sheetList}>
            {menu?.items?.map((item, index) => item.heading
              ? <Text key={index} style={[styles.heading, { color: colors.textMuted }]}>{item.heading}</Text>
              : item.actions
                ? <View key={index} style={styles.row}>
                  <Text style={[styles.rowLabel, { color: colors.textSecondary }]}>{item.label}</Text>
                  <View style={styles.rowActions}>{item.actions.map(choice =>
                    <Pressable key={choice.label} accessibilityRole="button" accessibilityLabel={`${item.label}: ${choice.label}`}
                      onPress={() => choose(choice.onSelect)} style={({ pressed }) => [styles.choice, pressed && styles.pressed]}>
                      <Text style={[styles.choiceText, { color: colors.accent }]}>{choice.label}</Text>
                    </Pressable>)}</View>
                </View>
                : <Pressable key={index} accessibilityRole="button" accessibilityLabel={item.label}
                  onPress={() => choose(item.onSelect)} style={({ pressed }) => [styles.item, pressed && styles.pressed]}>
                  <Text style={[styles.itemText, { color: colors.textSecondary }]}>{item.label}</Text>
                </Pressable>)}
          </ScrollView>
        </View>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, paddingVertical: 8, paddingHorizontal: 10, borderWidth: 1, borderRadius: 8 },
  count: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  check: { fontSize: 14, fontWeight: '700' },
  countText: { fontSize: 14 },
  actions: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  action: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: 8 },
  glyph: { fontSize: 16, fontWeight: '700' },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.75 },
  deselect: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, paddingHorizontal: 6, borderRadius: 6 },
  deselectText: { fontSize: 13, fontWeight: '600' },
  overlay: { flex: 1, justifyContent: 'center', padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: FALLBACK_PALETTE.overlay },
  sheet: { maxHeight: '80%', borderWidth: 1, borderRadius: 12, paddingVertical: 10 },
  sheetTitle: { fontSize: 16, fontWeight: '600', paddingHorizontal: 16, paddingBottom: 8 },
  sheetList: { maxHeight: 420 },
  heading: { fontSize: 12, paddingHorizontal: 16, paddingVertical: 8 },
  item: { paddingHorizontal: 16, paddingVertical: 12 },
  itemText: { fontSize: 14 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingVertical: 8 },
  rowLabel: { flexShrink: 1, fontSize: 14 },
  rowActions: { flexDirection: 'row', gap: 4 },
  choice: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  choiceText: { fontSize: 12, fontWeight: '600' },
});
