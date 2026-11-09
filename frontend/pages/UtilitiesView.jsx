import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { CacheStatusCard } from '../ui/CacheStatusCard';
import { CopyField } from '../ui/CopyField';
import { InstallPromptCard } from '../ui/InstallPromptCard';

export const utilitiesLabels = {
  title: 'Clipboard and install',
  copy: 'Copy a URL or diagnostic report, install the app and inspect the static cache.',
  copyHeading: 'Copy controls',
  installHeading: 'Install and launch',
  cacheHeading: 'Static cache',
};

// Utility-page composition for the copy, install and static-cache surfaces.
// The adapter owns clipboard, install and service-worker platform behavior.
export function UtilitiesView({
  copyFields = [],
  onCopy,
  install = {},
  installState = {},
  cache = {},
  cacheStatus = {},
  labels = {},
  palette = {},
  buttonPalette = {},
  icons = {},
}) {
  const copy = { ...utilitiesLabels, ...(labels || {}) };
  return <View style={styles.page}>
    <View style={styles.heading}>
      <Text role="heading" aria-level={2} style={[styles.title, { color: palette.text || '#fafafa' }]}>{copy.title}</Text>
      <Text style={[styles.copy, { color: palette.textMuted || '#a1a1aa' }]}>{copy.copy}</Text>
    </View>
    {copyFields.length ? <View style={styles.section}>
      <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: palette.text || '#fafafa' }]}>{copy.copyHeading}</Text>
      {copyFields.map((field, index) => <CopyField key={field.id || field.label || index}
        {...field} onCopy={field.onCopy || onCopy}
        palette={palette} buttonPalette={buttonPalette} />)}
    </View> : null}
    {install && Object.keys(install).length ? <View style={styles.section}>
      <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: palette.text || '#fafafa' }]}>{copy.installHeading}</Text>
      <InstallPromptCard state={installState} palette={palette} buttonPalette={buttonPalette} {...install} />
    </View> : null}
    {cache && Object.keys(cache).length ? <View style={styles.section}>
      <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: palette.text || '#fafafa' }]}>{copy.cacheHeading}</Text>
      <CacheStatusCard status={cacheStatus} palette={palette} buttonPalette={buttonPalette} icons={icons} {...cache} />
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 20, minWidth: 0 },
  heading: { gap: 6 },
  title: { fontSize: 22, fontWeight: '600', lineHeight: 28 },
  copy: { fontSize: 13, lineHeight: 19 },
  section: { gap: 12, minWidth: 0 },
  sectionTitle: { fontSize: 16, fontWeight: '600', lineHeight: 22 },
});
