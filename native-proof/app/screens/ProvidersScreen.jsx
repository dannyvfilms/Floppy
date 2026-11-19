import React, { useCallback, useEffect, useState } from 'react';
import { ProvidersView } from '../../../frontend/pages/ProvidersView';
import { Button } from '../../../frontend/ui/Button';
import { createProvidersTransport, directoryFromPayload } from '../data/providersTransport';
import { integrationButtonPalette, integrationPalette } from './integrationPalette';
import { palette } from '../theme';
import { Text, View } from 'react-native';
import { SettingsSurface } from './SettingsScreen';

export const surface = {
  id: 'PROVIDERS',
  status: 'ported',
  title: 'Providers directory with connection status',
  where: 'Settings, Providers (web: /settings/providers)',
  note: 'Renders the shared ProviderDirectoryView from GET /api/v1/providers/. Search and filters are server-authoritative; pin writes POST /api/v1/providers/pin/. Rows open ProviderDetail.',
};

export default function ProvidersScreen({ onBack, navigate }) {
  const [transport] = useState(() => createProvidersTransport());
  const [state, setState] = useState(transport.mode === 'server' ? 'loading' : 'signedOut');
  const [model, setModel] = useState(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    setState('loading');
    transport.directory({})
      .then(payload => { if (active) { setModel(directoryFromPayload(payload)); setState('ready'); } })
      .catch(cause => { if (active) { setError(cause?.message || 'Providers could not be loaded.'); setState('error'); } });
    return () => { active = false; };
  }, [transport, reload]);

  const fetchItems = useCallback(async ({ filters }) => directoryFromPayload(await transport.directory(filters)).items, [transport]);
  const colors = integrationPalette();
  const buttons = integrationButtonPalette();

  let body = null;
  if (state === 'ready') {
    body = <View style={{ gap: 12 }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        <Button label="Connections" tone="surface" palette={buttons} onPress={() => navigate?.('Connections')} />
        <Button label="Matching review" tone="surface" palette={buttons} onPress={() => navigate?.('MetadataReview')} />
      </View>
      <ProvidersView heading={false} palette={colors} buttonPalette={buttons}
      directory={{
        model: { ...model, setupUrl: '/setup/restart/' },
        onNavigate: url => { if (url === '/setup/restart/') navigate?.('Onboarding', { restart: true }); },
        skipInitialLoad: true,
        onFetch: fetchItems,
        onPin: async (item, { pinned }) => transport.pin(item.slug, pinned),
        onOpenProvider: item => navigate?.('ProviderDetail', { slug: item.slug, label: item.title }),
      }} />
    </View>;
  } else if (state === 'loading') {
    body = <Text style={{ color: palette.textMuted }}>Loading providers…</Text>;
  } else {
    const signedOut = state === 'signedOut';
    body = <>
      <Text accessibilityRole="alert" style={{ color: palette.danger }}>
        {signedOut ? 'Sign in to your Floppy server to manage providers.' : error}
      </Text>
      <Button label={signedOut ? 'Sign In' : 'Retry'} tone="surface" palette={buttons}
        onPress={signedOut ? () => navigate?.('Auth') : () => setReload(value => value + 1)} />
    </>;
  }
  return <SettingsSurface navigate={navigate}>{body}</SettingsSurface>;
}
