import React, { useCallback, useEffect, useState } from 'react';
import { Text } from 'react-native';
import { MetadataReviewView } from '../../../frontend/pages/MetadataReviewView';
import { Button } from '../../../frontend/ui/Button';
import {
  candidatesFromPayload,
  createMetadataReviewTransport,
  previewFromPayload,
  queueFromPayload,
} from '../data/metadataReviewTransport';
import { integrationButtonPalette, integrationPalette } from './integrationPalette';
import { palette } from '../theme';
import { SettingsSurface } from './SettingsScreen';

export const surface = {
  id: 'METADATA_REVIEW',
  status: 'ported',
  title: 'Matching review and match fix for movies and shows',
  where: 'Settings, Matching review (web: provider Activity review lists and /integrations/matches/<id>/)',
  note: 'GET /api/v1/metadata-review/ for the queue; per item candidates, preview and apply; POST .../references/<id>/ to ignore or remove. The preview token is validated again on apply, so a stale preview is refused.',
};

export default function MetadataReviewScreen({ params, onBack, navigate }) {
  const [transport] = useState(() => createMetadataReviewTransport());
  const [queue, setQueue] = useState(null);
  const [state, setState] = useState(transport.mode === 'server' ? 'loading' : 'signedOut');
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    transport.queue()
      .then(payload => { if (active) { setQueue(queueFromPayload(payload)); setState('ready'); } })
      .catch(cause => { if (active) { setError(cause?.message || 'The matching review could not be loaded.'); setState('error'); } });
    return () => { active = false; };
  }, [transport, reload]);

  const refresh = useCallback(() => setReload(value => value + 1), []);
  const colors = integrationPalette();
  const buttons = integrationButtonPalette();

  if (state === 'signedOut') {
    return <SettingsSurface navigate={navigate} active="providerActivity">
      <Text accessibilityRole="alert" style={{ color: palette.danger }}>Sign in to your Floppy server to review matches.</Text>
      <Button label="Sign In" tone="surface" palette={buttons} onPress={() => navigate?.('Auth')} />
    </SettingsSurface>;
  }
  return <SettingsSurface navigate={navigate} active="providerActivity">
    <MetadataReviewView queue={queue} state={state} error={error} palette={colors} buttonPalette={buttons}
      onRetry={() => { setState('loading'); refresh(); }}
      onChanged={refresh}
      onReference={(row, action) => transport.reference(row.id, action)}
      onSearch={async (itemId, options) => candidatesFromPayload(await transport.candidates(itemId, options))}
      onPreview={async (itemId, options) => previewFromPayload(await transport.preview(itemId, options))}
      onApply={(itemId, preview, options) => transport.apply(itemId, preview, options)}
      initialItem={params?.item} />
  </SettingsSurface>;
}
