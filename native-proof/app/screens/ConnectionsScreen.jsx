import React, { useCallback, useEffect, useState } from 'react';
import { ConnectionsView } from '../../../frontend/pages/ConnectionsView';
import { Button } from '../../../frontend/ui/Button';
import { Text } from 'react-native';
import { connectionsFromPayload, createConnectionsTransport, deviceFromPayload } from '../data/connectionsTransport';
import { integrationButtonPalette, integrationPalette } from './integrationPalette';
import { palette } from '../theme';
import { SettingsSurface } from './SettingsScreen';
import { createSettingsTransport } from '../data/settingsTransport';

export const surface = {
  id: 'CONNECTIONS',
  status: 'ported',
  title: 'Connections: services, sync direction, kill switch, conflicts, device approval',
  where: 'Settings, Connections (web: provider Connection tabs and the watched-state sync section)',
  note: 'GET /api/v1/connections/ for services and sync, POST .../direction/ and .../pause/, existing /api/v1/sync/conflicts/<id>/resolve/, GET and POST /api/v1/connections/device/ for device codes.',
};

export default function ConnectionsScreen({ onBack, navigate }) {
  const [transport] = useState(() => createConnectionsTransport());
  const [data, setData] = useState(null);
  const [state, setState] = useState(transport.mode === 'server' ? 'loading' : 'signedOut');
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    transport.load()
      .then(payload => { if (active) { setData(connectionsFromPayload(payload)); setState('ready'); } })
      .catch(cause => { if (active) { setError(cause?.message || 'Connections could not be loaded.'); setState('error'); } });
    return () => { active = false; };
  }, [transport, reload]);

  const refresh = useCallback(() => setReload(value => value + 1), []);
  const write = action => async (...args) => {
    const result = await action(...args);
    refresh();
    return result;
  };
  const colors = integrationPalette();
  const buttons = integrationButtonPalette();

  if (state === 'signedOut') {
    return <SettingsSurface navigate={navigate}>
      <Text accessibilityRole="alert" style={{ color: palette.danger }}>Sign in to your Floppy server to see your connections.</Text>
      <Button label="Sign In" tone="surface" palette={buttons} onPress={() => navigate?.('Auth')} />
    </SettingsSurface>;
  }
  return <SettingsSurface navigate={navigate}>
    <ConnectionsView data={data} state={state} error={error} palette={colors} buttonPalette={buttons}
      onRetry={() => { setState('loading'); refresh(); }}
      onOpenProvider={slug => navigate?.('ProviderDetail', { slug, tab: 'connection' })}
      onDirection={write((row, direction) => transport.setDirection(row.id, direction))}
      onPause={write((row, paused) => transport.setPaused(row.id, paused))}
      onResolve={write((conflict, watched) => transport.resolveConflict(conflict.id, watched))}
      device={{
        sessionRequired: !createSettingsTransport().canManageCredentials,
        lookup: async code => {
          const found = deviceFromPayload(await transport.lookupDevice(code));
          if (!found) throw new Error('That device code is not valid.');
          return found;
        },
        decide: (code, action) => transport.decideDevice(code, action),
      }} />
  </SettingsSurface>;
}
