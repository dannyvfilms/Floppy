import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BUTTON',
  title: 'Primary, surface and danger actions',
  where: 'Save bars, Load more, provider actions and confirmations',
  status: 'in_progress',
  note: 'The primary save, surface load-more and solid danger tones render here; the remaining hand-written and controls.jsx consumers are still migrating.',
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: radius.sm,
  focusStyle: { outlineStyle: 'solid', outlineWidth: 2, outlineColor: palette.accent, outlineOffset: 2 },
};

export default function ButtonSlot() {
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  function save() {
    setSaving(true);
    setStatus('Settings saved');
    setTimeout(() => setSaving(false), 600);
  }
  function sync() {
    setSyncing(true);
    setStatus('Sync started');
    setTimeout(() => setSyncing(false), 600);
  }
  return <View style={styles.group}>
    <Button label="Save settings" width="full" busy={saving}
      onPress={save} palette={buttonPalette} />
    <View style={styles.row}>
      <Button label={`Load more (${page})`} tone="surface"
        onPress={() => setPage(value => value + 1)} palette={buttonPalette} />
      <Button label="Delete list" tone="danger-solid"
        onPress={() => setStatus('Deleting needs confirmation on the list screen')} palette={buttonPalette} />
    </View>
    <View style={styles.row}>
      <Button label="Sync now" tone="surface" busy={syncing}
        onPress={sync} palette={buttonPalette} />
      <Button label="Disconnect" tone="danger-solid"
        onPress={() => setStatus('Disconnecting needs confirmation on the provider screen')} palette={buttonPalette} />
    </View>
    {status ? <Text style={styles.status}>{status}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  status: { color: palette.textMuted, fontSize: 12 },
});
