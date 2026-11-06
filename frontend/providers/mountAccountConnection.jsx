import React from 'react';
import { mountRoot } from '../settings/root';
import { ProviderSettingsView } from './ProviderSettingsView';
import { readThemePalette, submitNativeForm } from './transport.web';

function draftFromFallback(host, model) {
  const draft = {};
  for (const field of model.fields || []) {
    const input = host.querySelector(`[name="${field.name}"]`);
    if (input && input.value !== input.defaultValue) draft[field.name] = input.value;
  }
  return draft;
}

export function mountAccountConnection(host, model) {
  const draft = draftFromFallback(host, model);
  const colors = readThemePalette();
  const account = {
    ...model,
    fields: (model.fields || []).map(field => ({
      ...field,
      value: draft[field.name] ?? field.value,
    })),
  };

  return mountRoot(host, <ProviderSettingsView
    model={{ account, labels: model.labels }}
    tab="account"
    labels={model.labels}
    palette={colors}
    onConnect={values => submitNativeForm({
      action: model.connectUrl,
      csrf: model.csrf,
      returnTo: model.next,
      values,
    })}
    onDisconnect={instanceId => submitNativeForm({
      action: model.disconnectUrl,
      csrf: model.csrf,
      returnTo: model.next,
      values: instanceId ? { instance_id: instanceId } : {},
    })}
  />);
}
