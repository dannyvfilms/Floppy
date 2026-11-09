import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { ProviderFileImportView } from './ProviderFileImportView';
import { confirmAction, readThemePalette, submitNativeForm } from './transport.web';

function parentPreferences(host, model) {
  return host.closest('[x-data]')?.importPreferences || model.values || {};
}

function FileImportHost({ host, model }) {
  const [preferences, setPreferences] = useState(() => parentPreferences(host, model));

  useEffect(() => {
    const parent = host.closest('[x-data]');
    const change = event => setPreferences(event.detail);
    parent?.addEventListener('import-preferences-changed', change);
    return () => parent?.removeEventListener('import-preferences-changed', change);
  }, [host]);

  return <ProviderFileImportView
    model={model}
    preferences={preferences}
    palette={readThemePalette()}
    onSubmit={submitNativeForm}
    onOpenUrl={url => { if (url) window.open(url, '_blank', 'noopener'); }}
    onConfirm={confirmAction}
    onPickError={error => window.alert(error?.message || 'Could not read the selected file.')}
    onSubmitError={error => window.alert(error?.message || 'Could not start the import.')}
  />;
}

export function mountFileImport(host, model) {
  if (host.querySelector('input[type="file"]')?.files.length) return () => {};
  return mountRoot(host, <FileImportHost host={host} model={model} />);
}
