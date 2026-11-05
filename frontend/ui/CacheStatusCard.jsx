import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { SettingsCard } from '../settings/SettingsCard';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  background: '#27272a',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  success: '#10b981',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 8,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
  focusStyle: {},
};

const defaultCopy = {
  title: 'Static cache',
  badge: 'Web only',
  description: 'Service workers and the static cache belong to the browser app. They keep static assets available when the network is slow; tracking data still needs your Floppy server.',
  unavailable: 'The service worker status could not be read in this browser.',
  unsupportedBrowser: 'This browser does not support service workers.',
  unsupportedNative: 'Not available in the native app. Native builds update through the app distribution channel.',
  refreshLabel: 'Check status',
  labels: {
    registration: 'Service worker',
    active: 'Active worker',
    controlled: 'Page controlled',
    scope: 'Scope',
    caches: 'Static caches',
  },
  values: {
    registered: 'Registered',
    notRegistered: 'Not registered',
    active: 'Running',
    inactive: 'Not running',
    controlled: 'Yes',
    uncontrolled: 'No',
    unsupported: 'Unsupported',
    none: 'None',
  },
};

/** Web-specific service-worker and static-cache information. The browser
 * adapter supplies the state; native callers get the honest not-applicable copy.
 */
export function CacheStatusCard({
  status = {},
  onRefresh,
  busy = false,
  palette = {},
  buttonPalette = {},
  copy = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const text = { ...defaultCopy, ...copy, labels: { ...defaultCopy.labels, ...(copy.labels || {}) }, values: { ...defaultCopy.values, ...(copy.values || {}) } };
  const supported = status.supported !== false;
  const unsupportedCopy = status.reason === 'unsupported'
    ? text.unsupportedBrowser
    : status.reason === 'unavailable' ? text.unavailable : text.unsupportedNative;
  const caches = Array.isArray(status.cacheNames) && status.cacheNames.length
    ? status.cacheNames.join(', ')
    : text.values.none;
  const rows = supported ? [
    ['registration', status.registered ? text.values.registered : text.values.notRegistered],
    ['active', status.active ? text.values.active : text.values.inactive],
    ['controlled', status.controlled ? text.values.controlled : text.values.uncontrolled],
    ['scope', status.scope || '—'],
    ['caches', caches],
  ] : [];

  return <SettingsCard title={text.title} badge={text.badge} palette={colors}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>{text.description}</Text>
    {supported ? <View style={styles.rows}>
      {rows.map(([key, value]) => <View key={key} style={styles.row}>
        <Text style={[styles.label, { color: colors.textMuted }]}>{text.labels[key]}</Text>
        <Text style={[styles.value, { color: colors.text }]}>{value}</Text>
      </View>)}
    </View> : <Text style={[styles.copy, { color: colors.textMuted }]}>{unsupportedCopy}</Text>}
    {supported && onRefresh ? <View style={styles.action}>
      <Button label={text.refreshLabel} tone="surface" busy={busy} onPress={onRefresh} palette={buttons} />
    </View> : null}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 13, lineHeight: 19 },
  rows: { gap: 6 },
  row: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  label: { flexShrink: 0, fontSize: 12 },
  value: { flexShrink: 1, fontSize: 12, textAlign: 'right' },
  action: { alignItems: 'flex-start' },
});
