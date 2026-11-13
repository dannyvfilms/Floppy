import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { ProviderFileImportView } from './ProviderFileImportView';
import { confirmAction, pickBrowserFiles, readThemePalette, submitNativeForm } from './transport.web';

function parentPreferences(host, model) {
  return host.closest('[x-data]')?.importPreferences || model.values || {};
}

function FileImportHost({ host, model }) {
  const [preferences, setPreferences] = useState(() => parentPreferences(host, model));

  useEffect(() => {
    // The preferences React island and the file-import React island are often
    // siblings. Alpine is optional, so listen at their shared page boundary
    // instead of requiring an ancestor with x-data.
    const scope = host.closest('[data-settings-page-content]') || document;
    const change = event => setPreferences(event.detail);
    scope.addEventListener('import-preferences-changed', change);
    return () => scope.removeEventListener('import-preferences-changed', change);
  }, [host]);

  return <ProviderFileImportView
    model={{
      ...model,
      websiteLinkProps: model.website ? {
        href: model.website,
        hrefAttrs: { target: '_blank', rel: 'noopener noreferrer' },
      } : {},
    }}
    preferences={preferences}
    palette={readThemePalette()}
    onSubmit={submitNativeForm}
    pickFiles={pickBrowserFiles}
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
