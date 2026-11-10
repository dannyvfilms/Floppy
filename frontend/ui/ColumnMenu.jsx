import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  link: '#818cf8',
};

const FALLBACK_LABELS = {
  configure: 'Configure Table Columns',
  columns: 'Columns',
  moveUp: 'Move up',
  moveDown: 'Move down',
  hide: 'Hide column',
  show: 'Show column',
  reset: 'Reset to defaults',
  alwaysShown: 'Always shown',
  close: 'Close',
};

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...FALLBACK_LABELS, ...(labels || {}) };
}

function editableColumns(columns) {
  return (columns || []).filter(column => !column.fixed).map(column => ({ ...column }));
}

export function MediaColumnMenu({
  columns = [],
  defaultOrder,
  defaultHidden,
  palette,
  labels,
  onSave,
  disabled = false,
  compact = false,
  open: controlledOpen,
  onOpenChange,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [open, setOpen] = useState(false);
  const isOpen = controlledOpen === undefined ? open : controlledOpen;
  const [draft, setDraft] = useState(() => editableColumns(columns));

  useEffect(() => {
    setDraft(editableColumns(columns));
  }, [columns]);

  function changeOpen(next) {
    if (controlledOpen === undefined) {
      setOpen(next);
    }
    onOpenChange?.(next);
  }

  function commit(next) {
    setDraft(next);
    onSave?.({
      order: next.map(column => column.key),
      hidden: next.filter(column => !column.visible).map(column => column.key),
    });
  }

  function move(index, offset) {
    const target = index + offset;
    if (target < 0 || target >= draft.length) {
      return;
    }
    const next = [...draft];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    commit(next);
  }

  function toggle(index) {
    const next = draft.map((column, position) => position === index
      ? { ...column, visible: !column.visible }
      : column);
    commit(next);
  }

  function reset() {
    const order = defaultOrder && defaultOrder.length ? defaultOrder : columns.map(column => column.key);
    const hidden = new Set(defaultHidden || []);
    const byKey = new Map(columns.map(column => [column.key, column]));
    const next = order
      .map(key => byKey.get(key))
      .filter(Boolean)
      .map(column => ({ ...column, visible: !hidden.has(column.key) }));
    commit(next);
  }

  const fixed = (columns || []).filter(column => column.fixed);

  return <View style={styles.root}>
    <Pressable accessibilityRole="button" accessibilityLabel={copy.configure}
      accessibilityState={{ expanded: isOpen, disabled }}
      disabled={disabled}
      onPress={() => changeOpen(!isOpen)}
      style={[styles.trigger, compact && styles.triggerCompact, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      {compact
        ? <Icon spec={actionIcons.horizontalSliders} size={20} color={colors.textSecondary} />
        : <>
          <Text style={[styles.triggerGlyph, { color: colors.textSecondary }]}>☰</Text>
          <Text style={[styles.triggerText, { color: colors.textSecondary }]}>{copy.columns}</Text>
        </>}
    </Pressable>
    {isOpen ? <View style={[styles.menu, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <Text style={[styles.menuTitle, { color: colors.textMuted }]}>{copy.columns}</Text>
      <ScrollView style={styles.menuScroll} contentContainerStyle={styles.menuList}>
        {draft.map((column, index) => <View key={column.key} style={[styles.menuRow, { borderColor: colors.border }]}>
          <Text numberOfLines={1} style={[styles.columnLabel, {
            color: column.visible ? colors.textSecondary : colors.textMuted,
          }]}>{column.label || column.key}</Text>
          <View style={styles.actions}>
            <Pressable accessibilityRole="button"
              accessibilityLabel={`${copy.moveUp}: ${column.label || column.key}`}
              disabled={index === 0}
              onPress={() => move(index, -1)}
              style={styles.iconButton}>
              <Text style={[styles.iconText, { color: index === 0 ? colors.surfaceMuted : colors.textSecondary }]}>↑</Text>
            </Pressable>
            <Pressable accessibilityRole="button"
              accessibilityLabel={`${copy.moveDown}: ${column.label || column.key}`}
              disabled={index === draft.length - 1}
              onPress={() => move(index, 1)}
              style={styles.iconButton}>
              <Text style={[styles.iconText, {
                color: index === draft.length - 1 ? colors.surfaceMuted : colors.textSecondary,
              }]}>↓</Text>
            </Pressable>
            <Pressable accessibilityRole="button"
              accessibilityLabel={`${column.visible ? copy.hide : copy.show}: ${column.label || column.key}`}
              accessibilityState={{ checked: column.visible }}
              onPress={() => toggle(index)}
              style={styles.iconButton}>
              <Text style={[styles.iconText, { color: column.visible ? colors.textSecondary : colors.textMuted }]}>
                {column.visible ? '◉' : '○'}
              </Text>
            </Pressable>
          </View>
        </View>)}
        {fixed.map(column => <View key={column.key} style={[styles.menuRow, { borderColor: colors.border }]}>
          <Text numberOfLines={1} style={[styles.columnLabel, { color: colors.textSecondary }]}>
            {column.label || column.key}
          </Text>
          <Text style={[styles.fixedText, { color: colors.textMuted }]}>{copy.alwaysShown}</Text>
        </View>)}
      </ScrollView>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.reset} onPress={reset}
        style={[styles.reset, { borderColor: colors.border }]}>
        <Text style={[styles.resetText, { color: colors.link }]}>{copy.reset}</Text>
      </Pressable>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { position: 'relative', zIndex: 20 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 7 },
  triggerCompact: { width: 40, height: 40, padding: 0, justifyContent: 'center' },
  triggerGlyph: { fontSize: 14 },
  triggerText: { fontSize: 12, fontWeight: '600' },
  menu: { position: 'absolute', top: 40, right: 0, width: 260, borderWidth: 1, borderRadius: 8, overflow: 'hidden', zIndex: 30 },
  menuTitle: { fontSize: 10, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase', paddingHorizontal: 12, paddingVertical: 8 },
  menuScroll: { maxHeight: 320 },
  menuList: { paddingBottom: 4 },
  menuRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingHorizontal: 12, paddingVertical: 7 },
  columnLabel: { flex: 1, fontSize: 12 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  iconButton: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  iconText: { fontSize: 14, fontWeight: '700' },
  fixedText: { fontSize: 10 },
  reset: { borderTopWidth: 1, paddingHorizontal: 12, paddingVertical: 10 },
  resetText: { fontSize: 12, fontWeight: '600' },
});
