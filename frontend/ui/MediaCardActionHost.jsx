import { Modal, ModalCloseButton } from './Modal';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  border: '#3f3f46',
  text: '#fafafa',
  textMuted: '#a1a1aa',
  backdrop: 'rgba(0, 0, 0, 0.6)',
};

export function MediaCardActionHost({ action, open = false, labels = {}, palette, onClose, children }) {
  const colors = { ...FALLBACK_PALETTE, ...(palette || {}) };
  const closeLabel = labels.close || 'Close';
  return <Modal visible={!!open && !!action} transparent animationType="fade" onRequestClose={onClose}>
    <View style={styles.root}>
      <Pressable accessible={false} accessibilityLabel={closeLabel} onPress={onClose}
        style={[StyleSheet.absoluteFill, { backgroundColor: colors.backdrop }]} />
      <View accessibilityViewIsModal role="dialog" accessibilityLabel={action?.title || closeLabel}
        style={[styles.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.header}>
          <Text role="heading" aria-level={2} style={[styles.title, { color: colors.text }]}>{action?.title || ''}</Text>
          <ModalCloseButton accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose} style={styles.close}>
            <Text style={[styles.closeText, { color: colors.textMuted }]}>×</Text>
          </ModalCloseButton>
        </View>
        {children}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  dialog: { width: '100%', maxWidth: 420, borderWidth: 1, borderRadius: 12, padding: 16, gap: 8 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  title: { flexShrink: 1, fontSize: 15, fontWeight: '600' },
  close: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  closeText: { fontSize: 22, lineHeight: 24 },
});
