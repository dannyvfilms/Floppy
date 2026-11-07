import React from 'react';
import { mountRoot } from '../settings/root';
import { StremioAddonConfigurator } from './StremioConfigurator';
import { copyText } from './clipboard';

const palette = {
  panel: 'var(--color-panel)',
  surfaceDim: 'var(--color-surface-dim)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceHover: 'var(--color-surface-hover)',
  border: 'var(--color-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-accent)',
  accentContrast: 'var(--color-page-bg)',
  warning: 'var(--color-warning-text)',
  radius: 6,
  focusStyle: {},
};

function addonBaseUrl() {
  const path = window.location.pathname
    .replace(/\/configure\/?$/, '')
    .replace(/\/c\/[^/]*$/, '');
  return window.location.origin + path;
}

function Adapter({ props }) {
  return <StremioAddonConfigurator
    options={props.options || []}
    selectedIds={props.selectedIds || []}
    baseUrl={addonBaseUrl()}
    labels={props.labels}
    palette={palette}
    onCopy={copyText}
    onInstall={url => {
      window.location.assign(url.replace(/^https?:/, 'stremio:'));
    }} />;
}

export function mountStremioConfig(host, props) {
  return mountRoot(host, <Adapter props={props} />);
}
