import React, { useState } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import { Screen, Section } from '../components/Screen';
import { Button } from '../../../frontend/ui/Button';
import { DeviceConnectCard } from '../../../frontend/ui/DeviceConnect';
import { StremioAddonConfigurator } from '../../../frontend/ui/StremioConfigurator';
import { copyText } from '../../../frontend/ui/clipboard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'DEVICE-CONNECT',
  status: 'ported',
  title: 'Device connections and Stremio catalogs',
  where: 'Trakt device authorization and the Stremio addon configurator',
  note: 'Trakt device-code waiting, approval, expiry and error states plus Stremio publish toggles, ordering and generated install URLs render on this native placement. Server polling, redirects, credentials and browser/deep-link handoff stay in adapters; iOS and Android runtime interactions remain unverified.',
};

const uiPalette = {
  panel: palette.surface,
  surface: palette.surface,
  surfaceDim: palette.background,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceMuted,
  codeBackground: palette.background,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accentStrong,
  accentContrast: '#ffffff',
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  radius: radius.sm,
  focusStyle: { outlineStyle: 'solid', outlineWidth: 2, outlineColor: palette.accent, outlineOffset: 2 },
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  radius: radius.sm,
  focusStyle: uiPalette.focusStyle,
};

const CATALOG_OPTIONS = [
  { id: 'floppy-watchlist-movies', label: 'Watchlist', stremio_type: 'movie' },
  { id: 'floppy-watchlist-series', label: 'Watchlist', stremio_type: 'series' },
  { id: 'floppy-history-movies', label: 'History', stremio_type: 'movie' },
  { id: 'floppy-history-series', label: 'History', stremio_type: 'series' },
  { id: 'floppy-in-progress-movies', label: 'In Progress', stremio_type: 'movie' },
  { id: 'floppy-in-progress-series', label: 'In Progress', stremio_type: 'series' },
  { id: 'floppy-planning-series', label: 'Planning', stremio_type: 'series' },
];

const SELECTED = ['floppy-watchlist-movies', 'floppy-watchlist-series', 'floppy-history-series'];

function deviceError(state) {
  if (state === 'error') return 'Trakt authorization was denied. Try again or use a profile import.';
  return '';
}

export default function ConnectionsScreen({ onBack }) {
  const [deviceState, setDeviceState] = useState('waiting');
  const [config, setConfig] = useState({ selected: SELECTED, order: CATALOG_OPTIONS.map(option => option.id) });
  const [notice, setNotice] = useState('');

  async function open(url) {
    try {
      await Linking.openURL(url);
      setNotice('Opened the authorization page.');
    } catch (error) {
      setNotice('The platform could not open that link.');
    }
  }

  async function install(url) {
    try {
      await Linking.openURL(url.replace(/^https?:/, 'stremio:'));
      setNotice('Handed the install URL to Stremio.');
    } catch (error) {
      setNotice('Stremio is not installed on this device.');
    }
  }

  return <Screen title="Connections" subtitle="Trakt device code and Stremio catalogs" onBack={onBack}>
    <Section title="Trakt device authorization" copy="Use a code when Trakt cannot redirect back to a plain-HTTP server.">
      <DeviceConnectCard
        code="5055CC52"
        state={deviceState}
        error={deviceError(deviceState)}
        title="Connect Trakt"
        description="This instance is not served over HTTPS, so Trakt will not accept a browser redirect. Enter this code on Trakt instead."
        palette={uiPalette}
        onCopy={copyText}
        onOpen={() => open('https://trakt.tv/activate/5055CC52')}
        onCancel={() => setNotice('Cancelled the device authorization.')}
        onRetry={() => setDeviceState('waiting')} />
      <View style={styles.row}>
        <Button label="Simulate approval" tone="surface" onPress={() => setDeviceState('approved')} palette={buttonPalette} />
        <Button label="Simulate expiry" tone="surface" onPress={() => setDeviceState('expired')} palette={buttonPalette} />
        <Button label="Simulate error" tone="surface" onPress={() => setDeviceState('error')} palette={buttonPalette} />
        <Button label="Reset" tone="surface" onPress={() => setDeviceState('waiting')} palette={buttonPalette} />
      </View>
    </Section>

    <Section title="Stremio addon catalogs" copy="Choose which catalogs the addon publishes and the order Stremio shows them in.">
      <StremioAddonConfigurator
        options={CATALOG_OPTIONS}
        selectedIds={SELECTED}
        baseUrl="https://floppy.example.com/stremio-addon/demo-token"
        palette={uiPalette}
        onCopy={copyText}
        onInstall={install}
        onConfigurationChange={setConfig} />
      <Text style={styles.summary}>
        {`Publishing ${config.selected.length} catalogs. Order: ${config.order.length} entries.`}
      </Text>
    </Section>

    {notice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text> : null}
  </Screen>;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  summary: { color: palette.textMuted, fontSize: 12 },
  notice: { color: palette.textSecondary, fontSize: 12 },
});
