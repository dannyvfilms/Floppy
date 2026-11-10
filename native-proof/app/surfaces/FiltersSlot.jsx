import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { Icon } from '../../../frontend/ui/Icon';
import { Modal } from '../../../frontend/ui/Modal';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { mediaCardPalette, palette, radius, spacing } from '../theme';

export const surface = {
  id: 'FILTERS',
  title: 'Filter toolbar',
  where: 'Library',
  status: 'ported',
  note: 'The toolbar is the web row: the filter menu (All), Status and Sort with its direction arrow, over the real library query. The filter menu lists every web section with the real option lists from /api/v1/media/{type}/filter-options/, and the screen owns the filter state and reloads /api/v1/media/ with the same parameters the API media-list contract accepts. The view settings menu (gear) holds the Table/Grid switch and Select Items.',
};

const filterPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: mediaCardPalette.chipText,
  danger: palette.danger,
  disabled: palette.textMuted,
  overlay: mediaCardPalette.chipBackground,
  radius: radius.md,
};

const toolbarLabels = {
  filters: 'Filters',
  status: 'Status',
  allStatuses: 'Status',
  statuses: 'Statuses',
  sort: 'Sort',
};

// Presentational only: the Library screen owns the filter state and the
// transport call, so every control here changes the real server query.
export default function FiltersSlot({
  filters = {},
  options = {},
  busy = false,
  onChange,
}) {
  return <View style={styles.group}>
    <FilterBar
      variant="toolbar"
      filters={filters}
      options={options}
      palette={filterPalette}
      busy={busy}
      labels={toolbarLabels}
      onChange={onChange} />
  </View>;
}

// The gear in the page heading: web's "view settings" menu
// (media_settings_menu.html): Table/Grid, Share View, Save View and Select
// Items, the matching-entry preference, then the viewer's saved views.
export function LibrarySettingsMenu({
  view,
  canToggleView = true,
  canSelect,
  selectMode,
  onChangeView,
  onToggleSelect,
  onShare,
  onSave,
  savedViews = [],
  onApplySaved,
  onDeleteSaved,
  separateEntries,
  onToggleSeparate,
}) {
  const [open, setOpen] = useState(false);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [sharing, setSharing] = useState(false);
  const [notice, setNotice] = useState('');
  const items = [
    canToggleView ? {
      key: 'view',
      label: view === 'grid' ? 'Table View' : 'Grid View',
      icon: view === 'grid' ? 'table' : 'grid',
      onPress: () => onChangeView(view === 'grid' ? 'table' : 'grid'),
    } : null,
    onToggleSeparate ? {
      key: 'separate', label: 'Show matching entries separately',
      icon: 'eye', onPress: onToggleSeparate,
    } : null,
    canToggleView || onToggleSeparate ? { key: 'separator' } : null,
    onShare ? {
      key: 'share',
      label: sharing ? 'Sharing…' : 'Share View',
      icon: 'link',
      onPress: async () => {
        setSharing(true);
        try { await onShare(); } catch (cause) { setNotice(cause?.message || 'The view could not be shared.'); }
        setSharing(false);
      },
    } : null,
    onSave ? { key: 'save', label: 'Save View', icon: 'save', onPress: () => { setName(''); setNotice(''); setNaming(true); } } : null,
    canSelect ? {
      key: 'select',
      label: selectMode ? 'Cancel Select' : 'Select Items',
      icon: 'tag',
      onPress: onToggleSelect,
    } : null,
  ].filter(Boolean);

  async function submitName() {
    const trimmed = name.trim();
    if (!trimmed) { setNotice('Give the view a name.'); return; }
    try {
      await onSave(trimmed);
      setNaming(false);
    } catch (cause) {
      setNotice(cause?.message || 'The view could not be saved.');
    }
  }

  return <View>
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="View settings"
      accessibilityState={{ expanded: open }}
      onPress={() => setOpen(true)}
      style={({ pressed }) => [styles.gear, pressed && styles.pressed]}>
      <Icon spec={actionIcons.settings} size={22} color={palette.textSecondary} />
    </Pressable>
    <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.overlay}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close menu"
          style={styles.backdrop} onPress={() => setOpen(false)} />
        <View style={styles.menu}>
          {items.map(item => item.key === 'separator' ? <View key={item.key} accessibilityRole="separator" style={styles.separator} /> : <Pressable
            key={item.key}
            accessibilityRole="button"
            aria-pressed={item.key === 'separate' ? Boolean(separateEntries) : undefined}
            onPress={() => { setOpen(false); item.onPress(); }}
            style={({ pressed }) => [styles.menuItem, pressed && styles.pressed]}>
            <Icon spec={actionIcons[item.icon]} size={16} color={palette.textSecondary} />
            <Text style={styles.menuText}>{item.label}</Text>
            {item.key === 'separate' ? <Text style={{ marginLeft: 'auto', fontSize: 12, color: palette.textMuted }}>{separateEntries ? 'On' : 'Off'}</Text> : null}
          </Pressable>)}
          {savedViews.length ? <View style={styles.separator} /> : null}
          {savedViews.map(saved => <View key={saved.id} style={styles.savedRow}>
            <Pressable accessibilityRole="button" style={styles.savedName}
              onPress={() => { setOpen(false); onApplySaved?.(saved); }}>
              <Text numberOfLines={1} style={styles.menuText}>{saved.name}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${saved.name}`}
              onPress={() => onDeleteSaved?.(saved)} style={styles.savedDelete}>
              <Icon spec={actionIcons.x} size={14} color={palette.textMuted} />
            </Pressable>
          </View>)}
        </View>
      </View>
    </Modal>
    <Modal transparent visible={naming || Boolean(notice)} animationType="fade"
      onRequestClose={() => { setNaming(false); setNotice(''); }}>
      <View style={styles.center}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close"
          style={styles.backdrop} onPress={() => { setNaming(false); setNotice(''); }} />
        <View style={styles.dialog}>
          {naming ? <>
            <Text accessibilityRole="header" style={styles.dialogTitle}>Save View</Text>
            <TextInput accessibilityLabel="View name" autoFocus value={name} onChangeText={setName}
              onSubmitEditing={submitName} placeholder="Name this view" placeholderTextColor={palette.textMuted}
              style={styles.input} />
          </> : null}
          {notice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text> : null}
          <View style={styles.dialogActions}>
            <Pressable accessibilityRole="button" onPress={() => { setNaming(false); setNotice(''); }} style={styles.dialogButton}>
              <Text style={styles.menuText}>{naming ? 'Cancel' : 'Close'}</Text>
            </Pressable>
            {naming ? <Pressable accessibilityRole="button" onPress={submitName} style={[styles.dialogButton, styles.dialogPrimary]}>
              <Text style={styles.primaryText}>Save</Text>
            </Pressable> : null}
          </View>
        </View>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  gear: {
    width: 38,
    height: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 10,
    backgroundColor: palette.surface,
  },
  pressed: { opacity: 0.72 },
  overlay: { flex: 1, justifyContent: 'flex-start', alignItems: 'flex-end', padding: spacing.lg, paddingTop: 96 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: mediaCardPalette.chipBackground },
  menu: {
    width: 256,
    paddingVertical: spacing.xs,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: palette.border,
    backgroundColor: palette.surfaceStrong,
  },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  menuText: { color: palette.textSecondary, fontSize: 14, flexShrink: 1 },
  separator: { height: 1, marginVertical: spacing.xs, backgroundColor: palette.border },
  savedRow: { flexDirection: 'row', alignItems: 'center', paddingLeft: spacing.lg },
  savedName: { flex: 1, paddingVertical: spacing.md },
  savedDelete: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  dialog: { width: '100%', maxWidth: 360, gap: spacing.md, padding: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surfaceStrong },
  dialogTitle: { color: palette.text, fontSize: 18, fontWeight: '700' },
  input: { color: palette.text, borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, padding: spacing.md, backgroundColor: palette.surface },
  notice: { color: palette.textSecondary, fontSize: 14 },
  dialogActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  dialogButton: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.md },
  dialogPrimary: { backgroundColor: palette.accentStrong },
  primaryText: { color: mediaCardPalette.chipText, fontSize: 14, fontWeight: '600' },
});
