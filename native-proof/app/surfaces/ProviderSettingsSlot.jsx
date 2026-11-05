import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from '../../../frontend/settings/Chip';
import { AccountSettings } from '../../../frontend/providers/AccountSettings';
import { ConnectionSettings } from '../../../frontend/providers/ConnectionSettings';
import { ImportSettings } from '../../../frontend/providers/ImportSettings';
import { SetupGuide } from '../../../frontend/ui/SetupGuide';
import { Section } from '../components/Screen';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'SET-PROVIDERS',
  title: 'Provider Connection and Import settings',
  where: 'Settings provider connection, import and setup guide',
  status: 'ported',
  note: 'Provider credential, account, import and setup-guide forms render from shared React Native components with local edit, busy, saved and error state; server transport, secure credential storage and runtime device verification remain unverified.',
};

const settingsPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  border: palette.border,
  background: palette.surface,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const mediaPalette = { ...settingsPalette, badgeBorder: palette.border, badgeBackground: palette.surfaceStrong, badgeText: palette.textSecondary };

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function ProviderHeading({ name, media }) {
  return <View style={styles.providerHeading}>
    <Text role="heading" aria-level={3} style={styles.providerName}>{name}</Text>
    <View style={styles.mediaRow}>{media.map(item => <Chip key={item} label={item} pill palette={mediaPalette} />)}</View>
  </View>;
}

const connection = {
  title: 'AniList credentials',
  providerLabel: 'AniList',
  statusLabel: 'Connected',
  statusTone: 'success',
  description: 'Client credentials let Floppy complete private AniList imports. Public imports only need a username.',
  editable: true,
  canClear: true,
  getKeyUrl: 'https://anilist.co/settings/developer',
  getKeyLabel: 'Get a key from {name}',
  fields: [
    { name: 'client_id', label: 'Client ID', type: 'text', placeholder: 'AniList client ID', required: true, stored: true },
    { name: 'client_secret', label: 'Client secret', type: 'password', placeholder: 'AniList client secret', required: true, stored: true, maskedPreview: '••••••••' },
  ],
  personalFields: [
    { name: 'client_id', label: 'Client ID', type: 'text', placeholder: 'Your client ID', required: true },
    { name: 'client_secret', label: 'Client secret', type: 'password', placeholder: 'Your client secret', required: true },
  ],
  labels: {
    save: 'Save instance credentials',
    saved: 'Instance credentials saved',
    personalSave: 'Save personal key',
    personalSaved: 'Personal key saved',
  },
};

const guide = {
  title: 'AniList OAuth setup',
  description: 'Register a developer client so Floppy can finish private imports.',
  badge: { label: 'Setup required', tone: 'info', summary: 'The redirect URL must match the client you register.' },
  primary: { label: 'Redirect URL', key: 'redirect' },
  heading: 'Setup Instructions',
  collapsed: true,
  steps: [
    [['t', 'Open '], ['a', 'AniList developer settings', 'https://anilist.co/settings/developer'], ['t', ' and create a new client.']],
    [['t', 'Set the redirect URL to:'], ['copy', 'redirect']],
    [['t', 'Copy the client ID and secret into '], ['b', 'Connection'], ['t', ' above.']],
  ],
};

const copy = { redirect: 'https://floppy.example.com/providers/anilist/callback' };

const importModel = {
  title: 'Import options',
  description: 'Import anime and manga from your AniList profile.',
  configured: true,
  privateImport: false,
  username: 'demo_user',
  preferences: {
    title: 'Import preferences',
    editable: true,
    values: { mode: 'new', frequency: 'daily', time: '03:00', watchlistStatus: 'planning', watchlistTag: '' },
    statuses: [{ value: 'planning', label: 'Planning' }, { value: 'current', label: 'Watching' }, { value: 'completed', label: 'Completed' }],
    tags: [{ value: '', label: 'No tag' }, { value: 'anime', label: 'anime' }],
  },
};

const account = {
  title: 'Kavita account',
  statusLabel: 'Connected',
  statusTone: 'success',
  description: 'Sync the books and comics Kavita has on disk.',
  editable: true,
  saved: true,
  connected: true,
  summary: { url: 'https://kavita.example.com', lastSync: 'Yesterday at 21:04' },
  fields: [
    { name: 'base_url', label: 'Server URL', type: 'url', placeholder: 'https://kavita.example.com', required: true },
    { name: 'api_key', label: 'API Key', type: 'password', placeholder: 'Leave blank to keep the saved key', required: true },
    { name: 'sync_interval_minutes', label: 'Sync every', type: 'select', value: '60',
      options: [{ value: '15', label: '15 minutes' }, { value: '30', label: '30 minutes' }, { value: '60', label: '60 minutes' }] },
  ],
  labels: { connect: 'Connect Kavita', reconnect: 'Save connection' },
};

export default function ProviderSettingsSlot() {
  const [openLink, setOpenLink] = useState('');

  return <Section title="Providers" copy="Connection, import and account settings for your services.">
    <View style={styles.provider}>
      <ProviderHeading name="AniList" media={['Anime', 'Manga']} />
      <ConnectionSettings model={connection} palette={settingsPalette} buttonPalette={buttonPalette}
        onSave={async () => { await wait(450); }}
        onClear={async () => { await wait(450); }}
        onOpenLink={() => setOpenLink('Opened the AniList developer settings in the demo state.')} />
      <SetupGuide guide={guide} copy={copy} palette={settingsPalette} buttonPalette={buttonPalette}
        labels={{ showSteps: 'Show setup steps', hideSteps: 'Hide setup steps' }}
        onCopy={async () => { await wait(250); }}
        onOpenLink={() => setOpenLink('Opened the setup link in the demo state.')} />
      <ImportSettings model={importModel} palette={settingsPalette} buttonPalette={buttonPalette}
        onImport={async () => { await wait(600); }}
        onSavePreferences={async () => { await wait(300); }}
        onConfigure={() => setOpenLink('Connection settings are shown above.')} />
    </View>
    <View style={styles.provider}>
      <ProviderHeading name="Kavita" media={['Books', 'Comics']} />
      <AccountSettings model={account} palette={settingsPalette} buttonPalette={buttonPalette}
        onConnect={async () => { await wait(500); }}
        onDisconnect={async () => { await wait(450); }} />
    </View>
    {openLink ? <Text style={styles.linkNotice}>{openLink}</Text> : null}
  </Section>;
}

const styles = StyleSheet.create({
  provider: { gap: spacing.sm },
  providerHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: spacing.sm },
  providerName: { color: palette.text, fontSize: 15, fontWeight: '600' },
  mediaRow: { flexDirection: 'row', gap: spacing.xs },
  linkNotice: { color: palette.textMuted, fontSize: 12 },
});
