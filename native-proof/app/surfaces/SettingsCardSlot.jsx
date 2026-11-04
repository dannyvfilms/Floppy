import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Chip } from '../../../frontend/settings/Chip';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'SETTINGS-CARD',
  title: 'Settings card and chip',
  where: 'Settings, provider Connection, Import and Activity',
  status: 'ported',
  note: 'Shared card heading, info chip, status chip and body layout for settings and provider screens.',
};

const settingsPalette = {
  text: palette.text,
  border: palette.border,
  background: palette.surface,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
};

function Field({ label, value }) {
  return <View style={styles.field}>
    <Text style={styles.label}>{label}</Text>
    <Text style={styles.value}>{value}</Text>
  </View>;
}

export default function SettingsCardSlot() {
  const [helpOpen, setHelpOpen] = useState(false);
  return <>
    <SettingsCard title="Provider connection" badge="Read only"
      info_label="Why are these credentials read-only?"
      info_title="Read-only credential help" onInfo={() => setHelpOpen(true)}
      palette={settingsPalette}>
      <View style={styles.statusRow}>
        <Text style={styles.label}>Status</Text>
        <Chip label="Connected" palette={settingsPalette} />
      </View>
      <Field label="Server URL" value="https://floppy.example.com" />
      <Field label="API key" value="••••••••••••" />
      <Text style={styles.note}>Keys stay on your server. Floppy uses them only to read your library.</Text>
    </SettingsCard>
    <Modal transparent visible={helpOpen} animationType="fade"
      accessibilityViewIsModal onRequestClose={() => setHelpOpen(false)}>
      <View style={styles.backdrop}>
        <View style={styles.dialog}>
          <Text role="heading" aria-level={2} style={styles.dialogTitle}>Read-only credential help</Text>
          <Text style={styles.dialogCopy}>This connection uses an instance key supplied by the server owner, so it cannot be edited here. Ask the owner to rotate it in the provider settings.</Text>
          <Pressable accessibilityRole="button" onPress={() => setHelpOpen(false)} style={styles.close}>
            <Text style={styles.closeText}>Close</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  </>;
}

const styles = StyleSheet.create({
  statusRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  field: { gap: 2 },
  label: { color: palette.textMuted, fontSize: 12 },
  value: { color: palette.text, fontSize: 14 },
  note: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  backdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg, backgroundColor: 'rgba(0, 0, 0, 0.55)' },
  dialog: { gap: spacing.md, borderWidth: 1, borderColor: palette.surfaceMuted, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.lg },
  dialogTitle: { color: palette.text, fontSize: 16, fontWeight: '600' },
  dialogCopy: { color: palette.textSecondary, fontSize: 13, lineHeight: 19 },
  close: { alignSelf: 'flex-end', borderRadius: radius.sm, backgroundColor: palette.accentStrong, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  closeText: { color: '#fff', fontSize: 13, fontWeight: '600' },
});
