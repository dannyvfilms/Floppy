import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BUTTON',
  title: 'Primary, surface and danger actions',
  where: 'Save bars, Load more, provider actions and confirmations',
  status: 'ported',
  note: 'The shared action button renders here with the primary save, surface load-more and solid danger tones.',
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
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  function save() {
    setSaving(true);
    setStatus('Settings saved');
    setTimeout(() => setSaving(false), 600);
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
    {status ? <Text style={styles.status}>{status}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  status: { color: palette.textMuted, fontSize: 12 },
});
