import React from 'react';
import { mountRoot } from '../settings/root';
import { ProviderPage } from './ProviderPage';

export function mountProvider(host, model) {
  // Preserve edits made to the fallback while the lazy module was loading.
  // These are local drafts only; no saved keys arrive in the serialized model.
  const draft = { instance: {}, personal: {}, preferences: {} };
  for (const form of host.querySelectorAll('form')) {
    const scope = form.getAttribute('action') === model.credentials?.personalUrl ? 'personal' : 'instance';
    for (const input of form.querySelectorAll('input[name="client_id"], input[name="client_secret"]')) {
      if (!input.disabled && input.value !== input.defaultValue) draft[scope][input.name] = input.value;
    }
  }
  const username = host.querySelector('input[name="user"]');
  if (username && username.value !== username.defaultValue) draft.username = username.value;
  const privateImport = host.querySelector('input[x-model="usePrivateImport"]');
  if (privateImport?.checked) draft.privateImport = true;
  for (const [name, key] of [['import_frequency', 'frequency'], ['import_mode', 'mode'], ['import_time', 'time']]) {
    const field = host.querySelector(`[name="${name}"]`);
    if (!field) continue;
    const original = field.tagName === 'SELECT' ? [...field.options].find(option => option.defaultSelected)?.value ?? field.options[0].value : field.defaultValue;
    if (field.value !== original) draft.preferences[key] = field.value;
  }
  return mountRoot(host, <ProviderPage model={model} draft={draft} />);
}
