import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { palette, radius, spacing } from '../theme';

// "Add to custom lists" for a Discover card: the account's editable lists, one
// row each. Props only; the Discover surface loads the lists and saves.
export function DiscoverListPicker({ picker, onChoose, onClose }) {
  if (!picker) return null;
  const { title, lists, loading, error, savingId } = picker;
  return <Modal transparent visible animationType="fade" onRequestClose={onClose}>
    <View style={styles.overlay}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <Text style={styles.title}>Add to custom lists</Text>
        <Text style={styles.subtitle} numberOfLines={2}>{title}</Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {loading ? <Text style={styles.copy}>Loading lists...</Text> : null}
        {!loading && !error && !lists.length
          ? <Text style={styles.copy}>You have no lists you can add to yet. Create one from the Lists page.</Text>
          : null}
        <ScrollView style={styles.list}>
          {lists.map(list => <Pressable key={list.id} accessibilityRole="button"
            accessibilityLabel={`Add to ${list.name}`}
            disabled={savingId != null}
            onPress={() => onChoose(list)}
            style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}>
            <Text style={styles.rowText} numberOfLines={1}>{list.name}</Text>
            <Text style={styles.rowMeta}>{savingId === list.id ? 'Adding...' : `${list.itemsCount ?? 0} items`}</Text>
          </Pressable>)}
        </ScrollView>
        <Pressable accessibilityRole="button" onPress={onClose} style={styles.close}>
          <Text style={styles.closeText}>Close</Text>
        </Pressable>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: palette.overlay, justifyContent: 'center', padding: spacing.lg },
  sheet: { backgroundColor: palette.surface, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm, maxHeight: '80%' },
  title: { color: palette.text, fontSize: 18, fontWeight: '700' },
  subtitle: { color: palette.textMuted, fontSize: 13 },
  copy: { color: palette.textSecondary, fontSize: 14 },
  error: { color: palette.danger, fontSize: 13 },
  list: { flexGrow: 0 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, paddingVertical: 12, paddingHorizontal: spacing.md, borderRadius: radius.md },
  rowPressed: { backgroundColor: palette.surfaceStrong },
  rowText: { color: palette.text, fontSize: 15, flex: 1 },
  rowMeta: { color: palette.textMuted, fontSize: 12 },
  close: { alignItems: 'center', paddingVertical: spacing.sm },
  closeText: { color: palette.textSecondary, fontSize: 14, fontWeight: '600' },
});
