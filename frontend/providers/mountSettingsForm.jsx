import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { ProviderSettingsFormView } from './ProviderSettingsFormView';
import { confirmAction, readThemePalette, submitNativeForm } from './transport.web';

function preferencesFrom(host, form) {
  return host.closest('[x-data]')?.importPreferences || { mode: form.hidden?.mode };
}

function SettingsFormHost({ host, form }) {
  const [preferences, setPreferences] = useState(() => preferencesFrom(host, form));

  useEffect(() => {
    if (!form.followPreferences) return undefined;
    const parent = host.closest('[x-data]');
    const change = event => setPreferences(event.detail);
    parent?.addEventListener('import-preferences-changed', change);
    return () => parent?.removeEventListener('import-preferences-changed', change);
  }, [form.followPreferences, host]);

  return <ProviderSettingsFormView
    form={form}
    preferences={preferences}
    palette={readThemePalette()}
    onSubmit={submitNativeForm}
    onConfirm={confirmAction}
    onSubmitError={error => window.alert(error?.message || 'Could not save these settings.')}
  />;
}

export function mountSettingsForm(host, form) {
  return mountRoot(host, <SettingsFormHost host={host} form={form} />);
}
