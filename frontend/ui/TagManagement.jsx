import { Modal } from './Modal';
import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { BulkActionDialog, BulkOptionRow } from './BulkActions';
import { Button } from './Button';
import { Icon } from './Icon';
import { TextField } from './TextField';
import { Chip } from '../settings/Chip';
import { ConfirmDialog } from '../settings/ConfirmDialog';

const TAG_ICON = {
  viewBox: '0 0 24 24',
  root: {
    fill: 'none', stroke: 'currentColor', 'stroke-width': '2',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
  },
  children: [
    { tag: 'path', attrs: { d: 'M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z' }, children: [] },
    { tag: 'circle', attrs: { cx: '7.5', cy: '7.5', r: '.5', fill: 'currentColor' }, children: [] },
  ],
};

const TRASH_ICON = {
  viewBox: '0 0 24 24',
  root: {
    fill: 'none', stroke: 'currentColor', 'stroke-width': '2',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
  },
  children: [
    { tag: 'path', attrs: { d: 'M3 6h18' }, children: [] },
    { tag: 'path', attrs: { d: 'M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6' }, children: [] },
    { tag: 'path', attrs: { d: 'M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2' }, children: [] },
    { tag: 'line', attrs: { x1: '10', x2: '10', y1: '11', y2: '17' }, children: [] },
    { tag: 'line', attrs: { x1: '14', x2: '14', y1: '11', y2: '17' }, children: [] },
  ],
};

const FALLBACK_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: 10,
  focusStyle: {},
};

const SORTS = [
  { value: 'name', label: 'Name' },
  { value: 'count', label: 'Most used' },
];

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function chipPalette(colors, active) {
  return {
    badgeBorder: active ? colors.accentStrong : colors.border,
    badgeBackground: active ? colors.accentStrong : 'transparent',
    badgeText: active ? '#ffffff' : colors.textSecondary,
    badgeHover: active ? colors.accent : colors.surfaceMuted,
    interactiveStyle: {},
    focusStyle: {},
  };
}

const PREVIEW_TONES = {
  violet: { border: 'rgba(167, 139, 250, 0.18)', background: 'rgba(139, 92, 246, 0.07)' },
  slate: { border: 'rgba(148, 163, 184, 0.18)', background: 'rgba(100, 116, 139, 0.07)' },
  sky: { border: 'rgba(56, 189, 248, 0.18)', background: 'rgba(14, 165, 233, 0.07)' },
};

function previewChipPalette(colors, tone) {
  const appearance = PREVIEW_TONES[tone] || PREVIEW_TONES.slate;
  return {
    badgeBorder: appearance.border,
    badgeBackground: appearance.background,
    badgeText: colors.text,
    badgeHover: colors.surfaceMuted,
    interactiveStyle: {},
    focusStyle: {},
  };
}

function deleteMessage(tag) {
  return `Delete the "${tag.name}" tag from your library? This removes it from every item.`;
}

function TagDeleteDialog({ tag, palette, busy = false, onCancel, onConfirm }) {
  const colors = mergePalette(palette);
  return <ConfirmDialog
    visible={!!tag}
    title="Delete tag"
    message={tag ? deleteMessage(tag) : ''}
    warning={tag ? 'This removes the tag from every item that uses it.' : ''}
    confirmLabel="Delete tag"
    cancelLabel="Keep tag"
    busy={busy}
    palette={colors}
    onCancel={onCancel}
    onConfirm={onConfirm} />;
}

function TagTypeChips({ tag, palette, onOpenType }) {
  const colors = mergePalette(palette);
  const types = tag.types || [];
  if (!types.length) {
    return <Text style={[styles.muted, { color: colors.textMuted }]}>Not used yet</Text>;
  }
  return <View style={styles.chipRow}>
    {types.map(type => <Chip
      key={type.key}
      label={`${type.label} (${type.count})`}
      pill
      palette={{
        badgeBorder: 'transparent',
        badgeBackground: colors.surface,
        badgeText: colors.textSecondary,
        badgeHover: colors.surfaceMuted,
        interactiveStyle: { paddingVertical: 2, borderWidth: 0 },
        focusStyle: {},
      }}
      onPress={onOpenType ? () => onOpenType(tag, type) : undefined}
      accessibilityLabel={onOpenType ? `Open ${type.label} filtered by ${tag.name}` : undefined} />)}
  </View>;
}

function TagRow({ tag, palette, onDelete, onOpenType }) {
  const colors = mergePalette(palette);
  return <View style={[styles.tagRow, { backgroundColor: colors.surfaceStrong }]}>
    <View style={styles.tagBody}>
      <View style={styles.nameRow}>
        <Text style={{ color: colors.textMuted, fontSize: 16, lineHeight: 16 }}>
          <Icon spec={TAG_ICON}>{'#'}</Icon>
        </Text>
        <Text numberOfLines={1} style={[styles.tagName, { color: colors.text }]}>{tag.name}</Text>
        <Text style={[styles.count, { color: colors.textMuted }]}>{tag.count} {tag.count === 1 ? 'item' : 'items'}</Text>
      </View>
      <TagTypeChips tag={tag} palette={colors} onOpenType={onOpenType} />
    </View>
    <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${tag.name} tag`}
      onPress={() => onDelete?.(tag)}
      style={({ hovered }) => [styles.deleteButton, hovered && { backgroundColor: 'rgba(247, 89, 89, 0.12)' }]}>
      <Text style={{ color: colors.danger, fontSize: 16, lineHeight: 16 }}>
        <Icon spec={TRASH_ICON}>{'×'}</Icon>
      </Text>
    </Pressable>
  </View>;
}

export function TagIndex({
  tags = [],
  sort = 'name',
  query = '',
  palette,
  showControls = true,
  emptyText = 'No tags yet. Add tags to items from their detail page to see them here.',
  searchPlaceholder = 'Search tags...',
  onQueryChange,
  onSortChange,
  onDelete,
  onOpenType,
}) {
  const colors = mergePalette(palette);
  return <View style={styles.stack}>
    {showControls ? <>
      <TextField
        label="Search tags"
        labelHidden
        value={query}
        placeholder={searchPlaceholder}
        accessibilityLabel="Search tags"
        onChangeText={onQueryChange}
        palette={colors} />
      <View style={styles.chipRow}>
        {SORTS.map(option => <Chip
          key={option.value}
          label={option.label}
          palette={chipPalette(colors, sort === option.value)}
          pressed={sort === option.value}
          accessibilityLabel={`Sort tags by ${option.label}`}
          onPress={() => onSortChange?.(option.value)} />)}
      </View>
    </> : null}
    <View style={styles.indexList}>
      {tags.length
        ? tags.map(tag => <TagRow key={tag.id} tag={tag} palette={colors}
          onDelete={onDelete} onOpenType={onOpenType} />)
        : <Text style={[styles.empty, { color: colors.textSecondary }]}>{emptyText}</Text>}
    </View>
  </View>;
}

export function TagMediaFilter({
  options = [],
  active = 'all',
  allLabel = 'All',
  prompt = 'Browse by media type:',
  summary = true,
  palette,
  onSelect,
}) {
  const colors = mergePalette(palette);
  const all = useMemo(() => ({ key: 'all', label: allLabel }), [allLabel]);
  const choices = [all, ...options];
  const selected = choices.find(option => option.key === active) || all;
  return <View style={[styles.filterCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
    <Text style={[styles.filterPrompt, { color: colors.textSecondary }]}>{prompt}</Text>
    <View style={styles.chipRow}>
      {choices.map(option => <Chip
        key={option.key}
        label={option.count === undefined ? option.label : `${option.label} ${option.count}`}
        palette={chipPalette(colors, option.key === active)}
        pressed={option.key === active}
        accessibilityLabel={option.label}
        onPress={() => onSelect?.(option.key)} />)}
    </View>
    {summary ? <Text style={[styles.filterSummary, { color: colors.textMuted }]}>
      {`Showing ${selected.label}.`}
    </Text> : null}
  </View>;
}

export function TagPreview({
  sections = [],
  palette,
  onOpen,
  onOpenEntry,
}) {
  const colors = mergePalette(palette);
  return <View style={styles.stack}>
    {sections.map((section, index) => <View key={`${section.title}-${index}`}
      style={index ? [styles.previewSection, { borderColor: colors.border }] : null}>
      <Text style={[styles.previewTitle, { color: colors.textMuted }]}>
        {section.title_label || section.title}
      </Text>
      {section.entries && section.entries.length ? <View style={styles.chipRow}>
        {section.entries.map((entry, entryIndex) => <Chip
          key={`${entry.label}-${entryIndex}`}
          label={entry.label}
          pill
          palette={previewChipPalette(colors, section.tone)}
          accessibilityRole={entry.url ? 'link' : undefined}
          onPress={entry.url && onOpenEntry ? () => onOpenEntry(entry) : undefined} />)}
      </View> : section.empty_label ? <Pressable
        accessibilityRole="button"
        accessibilityLabel={section.empty_label}
        onPress={() => onOpen?.(section)}
        style={({ pressed }) => [styles.previewEmpty, {
          borderColor: colors.textMuted,
          backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
        }]}>
        <Text style={[styles.previewEmptyText, { color: colors.textSecondary }]}>
          {section.empty_label}
        </Text>
      </Pressable> : null}
    </View>)}
  </View>;
}

export function TagAssignmentDialog({
  open = false,
  embedded = false,
  showClose = true,
  item,
  tags = [],
  palette,
  busy = false,
  error = '',
  onToggle,
  onCreate,
  onDelete,
  onClose,
}) {
  const colors = mergePalette(palette);
  const [query, setQuery] = useState('');
  const [newName, setNewName] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return tags;
    return tags.filter(tag => tag.name.toLowerCase().includes(needle));
  }, [query, tags]);
  const canCreate = newName.trim().length > 0 && !busy;

  function close() {
    setQuery('');
    setNewName('');
    setDeleteTarget(null);
    onClose?.();
  }

  function createTag() {
    if (!canCreate) return;
    const created = onCreate?.(newName.trim());
    if (created !== false) setNewName('');
  }

  function confirmDelete() {
    if (!deleteTarget) return;
    onDelete?.(deleteTarget);
    setDeleteTarget(null);
  }

  const panel = <View style={[styles.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.dialogHead}>
      <View style={styles.dialogHeading}>
        <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: colors.text }]}>Tags</Text>
        {item ? <Text numberOfLines={2} style={[styles.dialogCopy, { color: colors.textMuted }]}>
          {item.title}{item.subtitle ? ` · ${item.subtitle}` : ''}
        </Text> : null}
      </View>
      {showClose ? <Button label="Close" tone="surface" disabled={busy}
        onPress={close} palette={colors} /> : null}
    </View>
    <TextField
      label="Search tags"
      labelHidden
      value={query}
      placeholder="Search your tags..."
      accessibilityLabel="Search tags"
      onChangeText={setQuery}
      palette={colors} />
    <ScrollView style={styles.tagScroll} keyboardShouldPersistTaps="handled">
      {filtered.length ? filtered.map(tag => <View key={tag.id}
        style={[styles.assignmentRow, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
        <View style={styles.assignmentBody}>
          <Text numberOfLines={1} style={[styles.tagName, { color: colors.text }]}>{tag.name}</Text>
          <Badge label={tag.hasTag ? 'Applied' : 'Not applied'} size="xs"
            palette={tag.hasTag
              ? { success: { backgroundColor: 'rgba(16, 185, 129, 0.14)', color: colors.success } }
              : { outline: { color: colors.textMuted, borderColor: colors.border, borderWidth: 1 } }}
            tone={tag.hasTag ? 'success' : 'outline'} />
        </View>
        <View style={styles.rowActions}>
          <Button label={tag.hasTag ? 'Remove' : 'Add'} tone={tag.hasTag ? 'surface' : 'primary'}
            disabled={busy || tag.owned === false}
            accessibilityLabel={`${tag.hasTag ? 'Remove' : 'Add'} ${tag.name} ${tag.hasTag ? 'from' : 'to'} this item`}
            onPress={() => onToggle?.(tag)} palette={colors} />
          <Button label="Delete" tone="ghost-danger" disabled={busy || tag.owned === false}
            accessibilityLabel={`Delete ${tag.name} tag`} onPress={() => setDeleteTarget(tag)}
            palette={colors} />
        </View>
      </View>) : <Text style={[styles.empty, { color: colors.textSecondary }]}>
        {tags.length ? 'No tags match this search.' : 'No tags yet. Create one below.'}
      </Text>}
    </ScrollView>
    <View style={[styles.createRow, { borderColor: colors.border }]}>
      <View style={styles.createField}>
        <TextField
          label="New tag"
          labelHidden
          value={newName}
          maxLength={50}
          placeholder="New tag..."
          accessibilityLabel="New tag name"
          onChangeText={setNewName}
          error={error}
          disabled={busy}
          palette={colors} />
      </View>
      <Button label="Add" disabled={!newName.trim() || busy} onPress={createTag} palette={colors} />
    </View>
  </View>;

  return <>
    {embedded ? panel : <Modal transparent visible={open} animationType="fade"
      accessibilityViewIsModal onRequestClose={close}>
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>{panel}</View>
    </Modal>}
    <TagDeleteDialog tag={deleteTarget} palette={colors} busy={busy}
      onCancel={() => setDeleteTarget(null)} onConfirm={confirmDelete} />
  </>;
}

export function TagBulkDialog({
  open = false,
  selectedItems = [],
  itemCount = 0,
  tags = [],
  selectedTag = '',
  action = 'add',
  busy = false,
  error = '',
  palette,
  onSelectTag,
  onActionChange,
  onApply,
  onClose,
}) {
  const colors = mergePalette(palette);
  const tag = tags.find(entry => entry.name === selectedTag);
  const count = selectedItems.length || itemCount;
  return <BulkActionDialog
    open={open}
    title="Apply Tag"
    description={`Choose one tag for ${count} selected ${count === 1 ? 'item' : 'items'}.`}
    confirmLabel={action === 'add' ? 'Add tag' : 'Remove tag'}
    cancelLabel="Cancel"
    busy={busy}
    confirmDisabled={!selectedTag || count === 0}
    palette={colors}
    onConfirm={onApply}
    onClose={onClose}>
    {selectedItems.length ? <View style={styles.bulkBlock}>
      <Text style={[styles.bulkHeading, { color: colors.textMuted }]}>Selected items</Text>
      {selectedItems.map(item => <Text key={item.id} numberOfLines={1}
        style={[styles.bulkItem, { color: colors.textSecondary }]}>
        {item.title}{item.detail ? ` · ${item.detail}` : ''}
      </Text>)}
    </View> : null}
    <View style={styles.bulkBlock}>
      <Text style={[styles.bulkHeading, { color: colors.textMuted }]}>Action</Text>
      {[{ value: 'add', label: 'Add tag' }, { value: 'remove', label: 'Remove tag' }].map(option =>
        <BulkOptionRow key={option.value} label={option.label} selected={action === option.value}
          palette={colors} onPress={() => onActionChange?.(option.value)} />)}
    </View>
    <View style={styles.bulkBlock}>
      <Text style={[styles.bulkHeading, { color: colors.textMuted }]}>Tag</Text>
      {tags.length ? tags.map(entry => <BulkOptionRow key={entry.id} label={entry.name}
        detail={Number.isFinite(entry.count)
          ? `${entry.count} ${entry.count === 1 ? 'item' : 'items'}`
          : undefined}
        selected={selectedTag === entry.name} palette={colors}
        onPress={() => onSelectTag?.(entry.name)} />) : <Text style={[styles.muted, { color: colors.textMuted }]}>
        No tags yet. Create a tag from an item first.
      </Text>}
      {tag ? <Text style={[styles.bulkNote, { color: colors.textMuted }]}>
        {`${action === 'add' ? 'Add' : 'Remove'} "${tag.name}" ${action === 'add' ? 'to' : 'from'} ${count} selected ${count === 1 ? 'item' : 'items'}.`}
      </Text> : null}
      {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    </View>
  </BulkActionDialog>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  indexList: { gap: 8 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tagRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 16, borderRadius: 6, padding: 16 },
  tagBody: { flex: 1, minWidth: 0, gap: 8 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  hash: { fontSize: 14, fontWeight: '700' },
  tagName: { flexShrink: 1, fontSize: 16, fontWeight: '500', lineHeight: 24 },
  count: { fontSize: 12 },
  deleteButton: { width: 32, height: 32, borderRadius: 6, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  muted: { fontSize: 12 },
  empty: { fontSize: 13, lineHeight: 19 },
  filterCard: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 10 },
  filterPrompt: { fontSize: 13 },
  filterSummary: { fontSize: 12 },
  previewSection: { borderTopWidth: 1, paddingTop: 12 },
  previewTitle: { fontSize: 11, fontWeight: '600', letterSpacing: 1.1, textTransform: 'uppercase' },
  previewEmpty: { alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8 },
  previewEmptyText: { fontSize: 14, fontWeight: '500' },
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: { width: '100%', maxWidth: 560, maxHeight: '88%', borderWidth: 1, borderRadius: 12, padding: 16, gap: 12 },
  dialogHead: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  dialogHeading: { flex: 1, gap: 2 },
  dialogTitle: { fontSize: 20, fontWeight: '700' },
  dialogCopy: { fontSize: 12, lineHeight: 17 },
  tagScroll: { maxHeight: 360 },
  assignmentRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10, borderWidth: 1, borderRadius: 8, padding: 10 },
  assignmentBody: { flex: 1, gap: 4 },
  rowActions: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  createRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, borderTopWidth: 1, paddingTop: 12 },
  createField: { flex: 1 },
  bulkBlock: { gap: 6 },
  bulkHeading: { fontSize: 12, fontWeight: '700', letterSpacing: 0.6 },
  bulkItem: { fontSize: 13 },
  bulkNote: { fontSize: 12, lineHeight: 17 },
  error: { fontSize: 12, lineHeight: 17 },
});
