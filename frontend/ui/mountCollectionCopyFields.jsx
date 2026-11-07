import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { CollectionCopyEditor } from './CollectionCopies';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent-strong)',
  accentContrast: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  focusStyle: {},
};

function CopyFieldsAdapter({ host, props }) {
  const [values, setValues] = useState(props.values || {});

  useEffect(() => {
    const form = host.closest('form');
    if (!form) return;
    form.querySelectorAll('input[data-collection-copy-hidden]').forEach((input) => input.remove());
    (props.fields || []).forEach((field) => {
      const value = values[field.name];
      if (field.type === 'checkbox') {
        if (!value) return;
      } else if (value === '' || value === null || value === undefined) {
        return;
      }
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = field.name;
      input.value = value === true ? 'on' : String(value);
      input.setAttribute('data-collection-copy-hidden', '');
      form.appendChild(input);
    });
  }, [host, props.fields, values]);

  return <CollectionCopyEditor
    fields={props.fields || []}
    values={values}
    errors={props.errors || {}}
    palette={palette}
    canMutate
    onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))} />;
}

export function mountCollectionCopyFields(host, props) {
  return mountRoot(host, <CopyFieldsAdapter host={host} props={props} />);
}
