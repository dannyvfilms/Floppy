import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Screen, Section } from '../components/Screen';
import AppearanceSettingsSlot from '../surfaces/AppearanceSettingsSlot';
import CardsSettingsSlot from '../surfaces/CardsSettingsSlot';
import HomeSettingsSlot from '../surfaces/HomeSettingsSlot';
import PreferencesSlot from '../surfaces/PreferencesSlot';
import ProviderSettingsSlot from '../surfaces/ProviderSettingsSlot';
import SettingsCardSlot from '../surfaces/SettingsCardSlot';
import { palette, radius, spacing } from '../theme';

function NavigationRow({ label, onPress }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
    style={({ pressed }) => [styles.row, pressed && styles.pressed]}>
    <Text style={styles.rowLabel}>{label}</Text>
    <Text style={styles.rowMeta}>Open</Text>
  </Pressable>;
}

export default function SettingsScreen({ navigate }) {
  return <Screen title="Settings" subtitle="Account, providers, appearance and data">
    <SettingsCardSlot />
    <ProviderSettingsSlot />
    <Section title="Screens">
      <NavigationRow label="Lists" onPress={() => navigate('Lists')} />
      <NavigationRow label="History" onPress={() => navigate('History')} />
      <NavigationRow label="Statistics" onPress={() => navigate('Statistics')} />
      <NavigationRow label="Search" onPress={() => navigate('Search')} />
    </Section>
    <PreferencesSlot />
    <AppearanceSettingsSlot />
    <CardsSettingsSlot />
    <HomeSettingsSlot />
  </Screen>;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, paddingHorizontal: spacing.md, paddingVertical: spacing.md },
  pressed: { opacity: 0.7 },
  rowLabel: { color: palette.text, fontSize: 15, fontWeight: '500' },
  rowMeta: { color: palette.accent, fontSize: 12 },
});
