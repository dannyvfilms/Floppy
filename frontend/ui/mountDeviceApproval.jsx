import React from 'react';
import { mountRoot } from '../settings/root';
import { DeviceApprovalCard } from './DeviceApproval';

const palette = {
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-indigo-600, #4f46e5)',
  accentContrast: '#ffffff',
  mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
};

function submit(method, fields, csrfToken) {
  const form = document.createElement('form');
  form.method = method;
  form.action = window.location.pathname;
  const all = method === 'post' ? { csrfmiddlewaretoken: csrfToken, ...fields } : fields;
  Object.entries(all).forEach(([name, value]) => {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.appendChild(input);
  });
  document.body.appendChild(form);
  form.submit();
}

export function mountDeviceApproval(host, props) {
  return mountRoot(host, <DeviceApprovalCard
    userCode={props.userCode}
    error={props.error}
    success={props.success}
    authorization={props.authorization}
    palette={palette}
    onContinue={code => submit('get', { user_code: code })}
    onDecide={action => submit('post', { user_code: props.userCode, action }, props.csrfToken)} />);
}
