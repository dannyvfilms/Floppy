import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'TRACKING',
  status: 'in_progress',
  title: 'Detail tracking and edit dialogs',
  where: 'Detail actions, episode and issue rows',
  note: 'The General, Tags, Metadata, Collection, Episode plays and Status history tracking tabs are being ported to shared React Native presentation. The web detail pages keep their server-rendered htmx and OOB save path, permissions and progressive fallback.',
};

export default function DetailTrackingSlot() {
  return <View style={[styles.root, { borderColor: palette.border }]}>
    <Text style={[styles.copy, { color: palette.textMuted }]}>Tracking dialog port in progress.</Text>
  </View>;
}

const styles = StyleSheet.create({
  root: { borderWidth: 1, borderRadius: 10, padding: spacing.md },
  copy: { fontSize: 13 },
});
