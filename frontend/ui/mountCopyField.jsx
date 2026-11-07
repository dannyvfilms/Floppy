import React from 'react';
import { mountRoot } from '../settings/root';
import { CopyField } from './CopyField';
import { copyText } from './clipboard.web';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  success: 'var(--color-status-clean)',
  danger: 'var(--color-error-text)',
  radius: 8,
  focusStyle: {},
};

const buttonPalette = {
  primary: {
    background: 'var(--color-accent)',
    pressed: 'var(--color-accent-strong)',
    hovered: 'var(--color-accent-strong)',
    text: '#ffffff',
    border: 'transparent',
  },
  surface: {
    background: 'var(--color-surface-strong)',
    pressed: 'var(--color-surface-muted)',
    hovered: 'var(--color-surface-muted)',
    text: 'var(--color-text)',
    border: 'var(--color-surface-border)',
  },
  radius: 6,
  focusStyle: {},
};

function CopyFieldAdapter({ props }) {
  return <CopyField {...props} onCopy={copyText}
    palette={palette} buttonPalette={buttonPalette} />;
}

export function mountCopyField(host, props) {
  return mountRoot(host, <CopyFieldAdapter props={props} />);
}
