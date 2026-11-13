import React from 'react';
import { mountRoot } from './root';
import { BackupStatus } from './BackupStatus';

// Theme values are resolved by the browser; the universal component only
// receives concrete presentation tokens.
const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surfaceStrong: 'var(--color-surface-strong)',
  warning: 'var(--color-warning-text)',
  fontFamily: 'inherit',
  monoFontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
};

export function mountBackupStatus(host, props) {
  return mountRoot(host, <BackupStatus sections={props} palette={palette} />);
}
