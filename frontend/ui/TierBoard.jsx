import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { Icon } from './Icon';
import { MediaCardActionHost } from './MediaCardActionHost';
import { MediaCard } from './MediaCard';
import { FormError, FormField, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  overlay: 'rgba(0, 0, 0, 0.6)',
};

const DEFAULT_LABELS = {
  title: 'Tiers',
  unranked: 'Unranked',
  addTier: 'Add tier',
  editTier: 'Edit tier',
  fillFromRatings: 'Fill from ratings',
  undo: 'Undo',
  exportImage: 'Export image',
  moveToTier: 'Move to tier',
  moveItem: 'Move item',
  moveUp: 'Move up',
  moveDown: 'Move down',
  earlier: 'Earlier',
  later: 'Later',
  name: 'Name',
  color: 'Color',
  customColor: 'Custom color',
  save: 'Save',
  cancel: 'Cancel',
  close: 'Close',
  deleteTier: 'Delete tier',
  showingFirst: 'Showing the first',
  showingRest: 'items. Filter the list to see the rest.',
  emptyTier: 'Drop items here',
  noTiers: 'This list has no tiers yet.',
  tierNameRequired: 'Give the tier a name.',
  tierNameLength: 'Tier names are up to 16 characters.',
  colorInvalid: 'Use a #rrggbb colour.',
  keepOneTier: 'Keep at least one tier.',
  moveDisabled: 'Only an editor can move items.',
  readOnly: 'Read-only tier board.',
  fillPlaced: 'Placed',
  fillNone: 'None of the unranked items have a rating.',
  fillFailed: 'Could not fill from ratings.',
  undoDone: 'Undone.',
  undoFailed: 'Could not undo.',
  smartNoTiers: 'Smart lists do not have tier boards.',
};

const COLORS = ['#ff7f7f', '#ffbf7f', '#ffdf7f', '#bfff7f', '#7fbfff', '#c4a7ff', '#ff9fd4', '#aab2bd'];
const COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/;

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function inkFor(color) {
  if (!COLOR_PATTERN.test(String(color || ''))) {
    return '#ffffff';
  }
  const red = parseInt(color.slice(1, 3), 16);
  const green = parseInt(color.slice(3, 5), 16);
  const blue = parseInt(color.slice(5, 7), 16);
  return 0.299 * red + 0.587 * green + 0.114 * blue > 153 ? '#1f2937' : '#ffffff';
}

function cardPalette(colors) {
  return {
    card: colors.surface,
    text: colors.text,
    textSecondary: colors.textSecondary,
    textMuted: colors.textMuted,
    border: colors.border,
    link: colors.accent,
    placeholder: colors.surfaceStrong,
    progressFill: colors.accent,
    chipText: colors.accentText,
  };
}

function tierCard(item) {
  return {
    mediaType: item.mediaType,
    shape: item.cardShape || 'poster',
    title: item.title,
    image: item.image || { src: null, fallback: '', source: 'primary' },
    statusChip: null,
    cornerChips: [],
    progressBar: null,
    lines: [],
    rating: item.rating || (item.score == null
      ? null
      : { label: String(item.score), value: item.score, scaleMax: 10 }),
    actions: null,
    titleLinks: [],
  };
}

function nextTierId(tiers) {
  let candidate = `t${Date.now().toString(36)}`;
  let suffix = 1;
  const used = new Set((tiers || []).map(tier => tier.id));
  while (used.has(candidate)) {
    candidate = `t${Date.now().toString(36)}${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function TierTile({ item, tierId, canEdit, tileWidth, colors, copy, onOpen, onMove }) {
  return <View style={[styles.tile, { width: tileWidth }]}>
    <MediaCard model={tierCard(item)} width={tileWidth} palette={cardPalette(colors)}
      onOpen={onOpen ? () => onOpen(item) : undefined} />
    {canEdit ? <Pressable accessibilityRole="button" accessibilityLabel={`${copy.moveItem}: ${item.title}`}
      onPress={() => onMove({ item, tierId })}
      style={({ pressed }) => [styles.moveButton, { backgroundColor: colors.overlay }, pressed && { opacity: 0.75 }]}>
      <Text style={[styles.moveGlyph, { color: colors.accentText }]}>↕</Text>
    </Pressable> : null}
  </View>;
}

function TierEditor({ editing, error, colors, copy, onChange, onShift, onDelete, onSave, onClose }) {
  const colorValue = String(editing.color || '');
  const nameErrors = [copy.tierNameRequired, copy.tierNameLength];
  const nameError = nameErrors.includes(error) ? error : undefined;
  const colorError = !COLOR_PATTERN.test(colorValue) ? copy.colorInvalid : undefined;
  const otherError = error && !nameErrors.includes(error) && error !== copy.colorInvalid ? error : undefined;
  return <MediaCardActionHost open action={{ title: editing.isNew ? copy.addTier : copy.editTier }}
    labels={{ close: copy.close }} palette={colors} onClose={onClose}>
    <FormTextField label={copy.name} value={editing.name}
      onChangeText={value => onChange({ name: value.slice(0, 16) })}
      error={nameError} palette={colors} />
    <FormField label={copy.color} palette={colors}>
      <View style={styles.colorRow}>
        {COLORS.map(color => <Pressable key={color} accessibilityRole="button"
          accessibilityLabel={`${copy.color} ${color}`}
          accessibilityState={{ selected: colorValue.toLowerCase() === color }}
          onPress={() => onChange({ color })}
          style={[styles.swatch, {
            backgroundColor: color,
            borderColor: colorValue.toLowerCase() === color ? colors.text : 'transparent',
            borderWidth: colorValue.toLowerCase() === color ? 2 : 0,
          }]} />)}
      </View>
    </FormField>
    <FormTextField label={copy.customColor} value={colorValue}
      onChangeText={value => onChange({ color: value })} palette={colors}
      placeholder="#4f46e5" error={colorError} />
    {!editing.isNew ? <View style={styles.dialogActions}>
      <Button label={copy.moveUp} tone="surface"
        disabled={editing.tiers[0]?.id === editing.id}
        onPress={() => onShift(-1)} palette={colors} />
      <Button label={copy.moveDown} tone="surface"
        disabled={editing.tiers[editing.tiers.length - 1]?.id === editing.id}
        onPress={() => onShift(1)} palette={colors} />
    </View> : null}
    <FormError message={otherError} palette={colors} />
    <View style={styles.dialogActions}>
      {!editing.isNew ? <Button label={copy.deleteTier} tone="danger-solid"
        onPress={onDelete} palette={colors} /> : null}
      <Button label={copy.save} tone="primary" onPress={onSave} palette={colors} />
      <Button label={copy.cancel} tone="surface" onPress={onClose} palette={colors} />
    </View>
  </MediaCardActionHost>;
}

function TierMove({ moving, tiers, colors, copy, onMoveTo, onReorder, onClose }) {
  const current = tiers.find(tier => tier.id === moving.tierId);
  return <MediaCardActionHost open action={{ title: moving.item.title }}
    labels={{ close: copy.close }} palette={colors} onClose={onClose}>
    <Text style={[styles.dialogHelp, { color: colors.textMuted }]}>
      {copy.moveToTier}{current ? `: ${current.name}` : ''}
    </Text>
    <View style={styles.chipRow}>
      {tiers.map(tier => <Pressable key={tier.id} accessibilityRole="button"
        accessibilityLabel={`${copy.moveToTier} ${tier.name}`}
        accessibilityState={{ selected: moving.tierId === tier.id }}
        onPress={() => onMoveTo(tier.id)}
        style={({ pressed }) => [styles.tierChoice, {
          backgroundColor: tier.color,
          borderColor: moving.tierId === tier.id ? colors.text : 'transparent',
          borderWidth: moving.tierId === tier.id ? 2 : 0,
        }, pressed && { opacity: 0.8 }]}>
        <Text style={[styles.tierChoiceText, { color: tier.ink || inkFor(tier.color) }]}>{tier.name}</Text>
      </Pressable>)}
      <Pressable accessibilityRole="button"
        accessibilityLabel={`${copy.moveToTier} ${copy.unranked}`}
        accessibilityState={{ selected: !moving.tierId }}
        onPress={() => onMoveTo('')}
        style={({ pressed }) => [styles.tierChoice, styles.unrankedChoice, {
          backgroundColor: colors.surface,
          borderColor: !moving.tierId ? colors.text : colors.border,
          borderWidth: !moving.tierId ? 2 : 1,
        }, pressed && { opacity: 0.8 }]}>
        <Text style={[styles.tierChoiceText, { color: colors.textSecondary }]}>{copy.unranked}</Text>
      </Pressable>
    </View>
    <View style={styles.dialogActions}>
      <Button label={copy.earlier} tone="surface" onPress={() => onReorder('up')} palette={colors} />
      <Button label={copy.later} tone="surface" onPress={() => onReorder('down')} palette={colors} />
    </View>
  </MediaCardActionHost>;
}

export function TierBoard({
  tiers = [],
  columns = [],
  unranked = [],
  canEdit = false,
  canFill = false,
  maxTiers = 12,
  truncated = false,
  truncatedCount = null,
  notice,
  undoAvailable = false,
  isSmart = false,
  labels,
  palette,
  onSaveTiers,
  onMoveItem,
  onReorderItem,
  onFillFromRatings,
  onUndoFill,
  onExport,
  onOpenItem,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const [editing, setEditing] = useState(null);
  const [moving, setMoving] = useState(null);
  const [error, setError] = useState('');
  const [localNotice, setLocalNotice] = useState('');
  const tileWidth = 92;
  const tierList = (columns || []).map(column => column.tier);
  const resolvedTiers = tiers.length ? tiers : tierList;
  const shownNotice = localNotice || notice || '';

  if (isSmart) {
    return <View style={[styles.empty, { backgroundColor: colors.surface }]}>
      <Text style={[styles.emptyText, { color: colors.textMuted }]}>{copy.smartNoTiers}</Text>
    </View>;
  }

  function openEdit(tier) {
    if (!canEdit) {
      return;
    }
    setError('');
    setEditing({
      id: tier.id,
      name: tier.name,
      color: tier.color,
      isNew: false,
      tiers: resolvedTiers.map(entry => ({ ...entry })),
    });
  }

  function openAdd() {
    if (!canEdit || resolvedTiers.length >= maxTiers) {
      return;
    }
    setError('');
    setEditing({
      id: nextTierId(resolvedTiers),
      name: '',
      color: COLORS[resolvedTiers.length % COLORS.length],
      isNew: true,
      tiers: resolvedTiers.map(entry => ({ ...entry })),
    });
  }

  function updateEditing(patch) {
    setError('');
    setEditing(current => ({ ...current, ...patch }));
  }

  function shiftEditing(offset) {
    setEditing(current => {
      if (!current || current.isNew) {
        return current;
      }
      const tiersDraft = current.tiers.map(entry => ({ ...entry }));
      const index = tiersDraft.findIndex(entry => entry.id === current.id);
      const target = index + offset;
      if (index < 0 || target < 0 || target >= tiersDraft.length) {
        return current;
      }
      const [entry] = tiersDraft.splice(index, 1);
      tiersDraft.splice(target, 0, entry);
      return { ...current, tiers: tiersDraft };
    });
  }

  function saveEditing() {
    if (!editing) {
      return;
    }
    const name = editing.name.trim();
    if (!name) {
      setError(copy.tierNameRequired);
      return;
    }
    if (name.length > 16) {
      setError(copy.tierNameLength);
      return;
    }
    if (!COLOR_PATTERN.test(String(editing.color || ''))) {
      setError(copy.colorInvalid);
      return;
    }
    const tiersDraft = editing.tiers.map(entry => ({ ...entry }));
    const index = tiersDraft.findIndex(entry => entry.id === editing.id);
    const next = { id: editing.id, name, color: editing.color.toLowerCase() };
    if (index === -1) {
      tiersDraft.push(next);
    } else {
      tiersDraft[index] = next;
    }
    onSaveTiers?.(tiersDraft);
    setEditing(null);
    setError('');
  }

  function deleteEditing() {
    if (!editing) {
      return;
    }
    if (editing.tiers.length <= 1) {
      setError(copy.keepOneTier);
      return;
    }
    const next = editing.tiers
      .filter(entry => entry.id !== editing.id)
      .map(entry => ({ ...entry }));
    onSaveTiers?.(next);
    setEditing(null);
    setError('');
  }

  function moveTo(tierId) {
    if (!moving) {
      return;
    }
    const target = tierId === ''
      ? unranked
      : (columns.find(column => column.tier.id === tierId)?.items || []);
    const itemIds = target.map(item => item.id).filter(id => id !== moving.item.id);
    onMoveItem?.({ itemId: moving.item.id, tierId, itemIds: [...itemIds, moving.item.id] });
    setMoving(null);
  }

  function reorder(direction) {
    if (!moving) {
      return;
    }
    onReorderItem?.({ itemId: moving.item.id, tierId: moving.tierId, direction });
    setMoving(null);
  }

  function fill() {
    try {
      const result = onFillFromRatings?.();
      if (result && result.placed != null) {
        setLocalNotice(result.placed
          ? `${copy.fillPlaced} ${result.placed}.`
          : copy.fillNone);
      } else {
        setLocalNotice(copy.fillNone);
      }
    } catch {
      setLocalNotice(copy.fillFailed);
    }
  }

  function undoFill() {
    try {
      onUndoFill?.();
      setLocalNotice(copy.undoDone);
    } catch {
      setLocalNotice(copy.undoFailed);
    }
  }

  return <View style={styles.board}>
    {truncated ? <Text style={[styles.truncated, { color: colors.textMuted }]}>
      {copy.showingFirst} {truncatedCount ?? ''} {copy.showingRest}
    </Text> : null}

    <View style={styles.rows}>
      {(columns || []).map(column => <View key={column.tier.id} style={[styles.row, { backgroundColor: colors.surface }]}>
        {canEdit ? <Pressable accessibilityRole="button" accessibilityLabel={`${copy.editTier}: ${column.tier.name}`}
          onPress={() => openEdit(column.tier)}
          style={({ pressed }) => [styles.label, {
            backgroundColor: column.tier.color,
          }, pressed && { opacity: 0.85 }]}>
          <Text style={[styles.labelText, { color: column.tier.ink || inkFor(column.tier.color) }]}>{column.tier.name}</Text>
          <Icon spec={actionIcons.edit} color={column.tier.ink || inkFor(column.tier.color)} size={14}
            style={[styles.labelGlyph, { color: column.tier.ink || inkFor(column.tier.color) }]}>{'✎'}</Icon>
        </Pressable> : <View style={[styles.label, { backgroundColor: column.tier.color }]}>
          <Text style={[styles.labelText, { color: column.tier.ink || inkFor(column.tier.color) }]}>{column.tier.name}</Text>
        </View>}
        <View style={styles.drop}>
          {(column.items || []).map(item => <TierTile key={item.id} item={item} tierId={column.tier.id}
            canEdit={canEdit} tileWidth={tileWidth} colors={colors} copy={copy}
            onOpen={onOpenItem} onMove={setMoving} />)}
          {!(column.items || []).length ? <Text style={[styles.emptyTier, { color: colors.textMuted }]}>{copy.emptyTier}</Text> : null}
        </View>
      </View>)}
      {!(columns || []).length ? <Text style={[styles.emptyText, { color: colors.textMuted }]}>{copy.noTiers}</Text> : null}
    </View>

    <View style={styles.boardActions}>
      {canEdit && resolvedTiers.length < maxTiers ? <Button label={copy.addTier} tone="surface"
        onPress={openAdd} palette={colors} /> : null}
      {canEdit && canFill && unranked.length > 0 ? <Button label={copy.fillFromRatings}
        tone="surface" onPress={fill} palette={colors} /> : null}
      {onExport ? <Button label={copy.exportImage} tone="surface" onPress={onExport} palette={colors} /> : null}
    </View>

    {shownNotice ? <View style={styles.noticeRow}>
      <Text style={[styles.notice, { color: colors.textMuted }]}>{shownNotice}</Text>
      {undoAvailable ? <Button label={copy.undo} tone="surface" onPress={undoFill} palette={colors} /> : null}
    </View> : null}

    <View style={[styles.unranked, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <Text style={[styles.unrankedTitle, { color: colors.textSecondary }]}>
        {copy.unranked} <Text style={{ color: colors.textMuted }}>{unranked.length}</Text>
      </Text>
      <View style={styles.drop}>
        {unranked.map(item => <TierTile key={item.id} item={item} tierId=""
          canEdit={canEdit} tileWidth={tileWidth} colors={colors} copy={copy}
          onOpen={onOpenItem} onMove={setMoving} />)}
        {!unranked.length ? <Text style={[styles.emptyTier, { color: colors.textMuted }]}>{copy.emptyTier}</Text> : null}
      </View>
    </View>

    {!canEdit ? <Text style={[styles.help, { color: colors.textMuted }]}>{copy.readOnly}</Text> : null}

    {editing ? <TierEditor editing={editing} error={error} colors={colors} copy={copy}
      onChange={updateEditing} onShift={shiftEditing} onDelete={deleteEditing}
      onSave={saveEditing} onClose={() => { setEditing(null); setError(''); }} /> : null}
    {moving ? <TierMove moving={moving} tiers={resolvedTiers} colors={colors} copy={copy}
      onMoveTo={moveTo} onReorder={reorder} onClose={() => setMoving(null)} /> : null}
  </View>;
}

const styles = StyleSheet.create({
  board: { gap: 10 },
  truncated: { fontSize: 12, lineHeight: 17 },
  rows: { gap: 4 },
  row: { flexDirection: 'row', minHeight: 64, borderRadius: 8, overflow: 'hidden' },
  label: { width: 72, alignItems: 'center', justifyContent: 'center', padding: 6, gap: 2 },
  labelText: { fontSize: 18, fontWeight: '700', textAlign: 'center' },
  labelGlyph: { fontSize: 11, opacity: 0.65 },
  drop: { flex: 1, minWidth: 0, flexDirection: 'row', flexWrap: 'wrap', alignContent: 'flex-start', gap: 6, padding: 6 },
  tile: { position: 'relative' },
  moveButton: { position: 'absolute', right: 4, bottom: 4, width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  moveGlyph: { fontSize: 13, fontWeight: '700' },
  emptyTier: { alignSelf: 'center', fontSize: 12 },
  boardActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  noticeRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  notice: { flexShrink: 1, fontSize: 12, lineHeight: 17 },
  unranked: { borderWidth: 2, borderStyle: 'dashed', borderRadius: 10, paddingTop: 8, paddingHorizontal: 6, paddingBottom: 6, gap: 4 },
  unrankedTitle: { fontSize: 13, fontWeight: '700', paddingHorizontal: 4 },
  empty: { borderRadius: 8, padding: 16 },
  emptyText: { fontSize: 13, lineHeight: 18 },
  help: { fontSize: 12, lineHeight: 17 },
  dialogHelp: { fontSize: 12, lineHeight: 17 },
  dialogActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  colorRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  swatch: { width: 30, height: 30, borderRadius: 15 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tierChoice: { minHeight: 36, minWidth: 36, borderRadius: 6, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  unrankedChoice: { borderWidth: 1 },
  tierChoiceText: { fontSize: 13, fontWeight: '700' },
});
