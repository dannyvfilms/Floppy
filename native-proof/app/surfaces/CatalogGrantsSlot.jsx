import React, { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import { CatalogGrantsCard } from '../../../frontend/settings/AccessSettings';
import { Button } from '../../../frontend/ui/Button';
import { copyText } from '../data/fileFlows';
import { grantsFromPayload } from '../data/settingsTransport';
import { useSettingsResource } from './useSettingsResource';

// Install credentials belong to the Stremio setup, as on its web Tracking tab.
// Keep the one-time credential in this adapter; presentation receives a slot.
function CatalogGrantsForm({ data, transport, palette, buttonPalette }) {
  const [grants, setGrants] = useState(() => grantsFromPayload(data));
  const [status, setStatus] = useState({ busy: false, error: '', success: '' });
  const [oneTimeSecret, setOneTimeSecret] = useState(null);
  const secretRef = useRef(null);

  useEffect(() => () => { secretRef.current = null; }, []);

  async function createGrant(values) {
    setStatus({ busy: true, error: '', success: '' });
    try {
      const created = await transport.createGrant(values);
      secretRef.current = created.secret;
      setOneTimeSecret({ id: created.id, name: created.name });
      setGrants(current => [...grantsFromPayload({ results: [created] }), ...current]);
      setStatus({ busy: false, error: '', success: `Created add-on install '${created.name}'. Copy the secret now; it is shown once.` });
    } catch (error) {
      setStatus({ busy: false, error: error?.message || 'Could not create the install credential.', success: '' });
      throw error;
    }
  }

  async function revokeGrant(grant) {
    setStatus({ busy: true, error: '', success: '' });
    try {
      await transport.revokeGrant({ id: grant.id });
      setGrants(current => current.filter(entry => entry.id !== grant.id));
      if (oneTimeSecret?.id === grant.id) {
        secretRef.current = null;
        setOneTimeSecret(null);
      }
      setStatus({ busy: false, error: '', success: `Revoked add-on install '${grant.name}'.` });
    } catch (error) {
      setStatus({ busy: false, error: error?.message || 'Could not revoke the install.', success: '' });
      throw error;
    }
  }

  async function copySecret() {
    try {
      if (!secretRef.current) throw new Error('The install secret is no longer available.');
      const copied = await copyText(secretRef.current);
      if (copied === false) throw new Error('Copy was cancelled. The secret is still available below.');
      setStatus(current => ({ ...current, error: '', success: 'One-time secret copied.' }));
    } catch (error) {
      setStatus(current => ({ ...current, error: error?.message || 'The secret could not be copied.', success: '' }));
    }
  }

  return <CatalogGrantsCard grants={grants} {...status}
    sessionRequired={!transport.canManageCredentials}
    oneTimeSecret={oneTimeSecret}
    secretSlot={oneTimeSecret ? <Text selectable accessibilityLabel="New install secret"
      style={{ color: palette.textSecondary, fontFamily: 'monospace', fontSize: 14, flex: 1 }}>{secretRef.current}</Text> : null}
    onCreate={createGrant} onRevoke={revokeGrant} onCopySecret={copySecret}
    palette={palette} buttonPalette={buttonPalette} />;
}

export default function CatalogGrantsSlot({ palette = {}, buttonPalette = {} }) {
  const resource = useSettingsResource(transport => transport.loadGrants());
  if (resource.state !== 'ready') {
    return <View style={{ gap: 12 }}>
      <Text accessibilityRole={resource.state === 'loading' ? undefined : 'alert'}
        style={{ color: resource.state === 'loading' ? palette.textMuted : palette.danger }}>
        {resource.state === 'loading' ? 'Loading install credentials…' : resource.message || 'Could not load install credentials.'}
      </Text>
      {resource.state === 'error' ? <Button label="Retry" tone="surface" palette={buttonPalette} onPress={resource.reload} /> : null}
    </View>;
  }
  return <CatalogGrantsForm data={resource.data} transport={resource.transport} palette={palette} buttonPalette={buttonPalette} />;
}
