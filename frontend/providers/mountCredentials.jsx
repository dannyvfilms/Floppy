import React from 'react';
import { mountRoot } from '../settings/root';
import { ProviderSettingsView } from './ProviderSettingsView';
import { readThemePalette, submitNativeForm } from './transport.web';

function draftFromFallback(host) {
  // Keep text typed into the server fallback while this module was loading.
  const draft = { instance: {}, personal: {} };
  for (const input of host.querySelectorAll('input[name]')) {
    if (input.type === 'hidden' || input.disabled || input.value === input.defaultValue) continue;
    draft[input.id.includes('-personal-') ? 'personal' : 'instance'][input.name] = input.value;
  }
  return draft;
}

export function mountCredentials(host, credentials) {
  const draft = draftFromFallback(host);
  const colors = readThemePalette();
  const model = {
    credentials: {
      ...credentials,
      fields: (credentials.fields || []).map(field => ({
        ...field,
        value: draft.instance[field.name] ?? '',
      })),
      personalFields: credentials.personalFields
        ? credentials.personalFields.map(field => ({
          ...field,
          value: draft.personal[field.name] ?? '',
        }))
        : undefined,
    },
    labels: credentials.labels,
  };

  return mountRoot(host, <ProviderSettingsView
    model={model}
    tab="connection"
    labels={credentials.labels}
    palette={colors}
    onSave={(kind, values) => submitNativeForm({
      action: kind === 'personal' ? credentials.personalUrl : credentials.saveUrl,
      csrf: credentials.csrf,
      returnTo: credentials.next,
      values,
    })}
    onClear={() => submitNativeForm({
      action: credentials.clearUrl,
      csrf: credentials.csrf,
      returnTo: credentials.next,
      values: {},
    })}
    onSetDefault={item => submitNativeForm({
      action: item?.action,
      csrf: credentials.csrf,
      returnTo: credentials.next,
      values: { source: credentials.slug },
    })}
    onOpenLink={url => { if (url) window.open(url, '_blank', 'noopener'); }}
    linkPropsForUrl={url => url ? {
      href: url,
      hrefAttrs: { target: '_blank', rel: 'noopener noreferrer' },
    } : {}}
  />);
}
