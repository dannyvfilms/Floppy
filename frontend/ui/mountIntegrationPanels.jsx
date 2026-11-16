import React from 'react';
import { mountRoot } from '../settings/root';
import { ArrLibraryPanels } from './IntegrationPanels';
import { copyText } from './clipboard.web';

const palette = {
  background: 'var(--color-surface-dim)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-info-text)',
  accentStrong: 'var(--color-accent-strong)',
  link: 'var(--color-link)',
  success: 'var(--color-success-text)',
  warning: 'var(--color-warning-text)',
  danger: 'var(--color-error-text)',
  // Follows the theme's corner radius, like the server panel's rounded classes.
  radius: 'var(--theme-radius)',
  focusStyle: {},
};

// The web renders Open-in links as real anchors so they open in a new tab and
// keep middle-click and copy-link behavior.
const linkProps = url => ({ href: url, hrefAttrs: { target: '_blank', rel: 'noopener noreferrer' } });

function startSearch(host, props, panel) {
  // Same POST the server fallback form sends; the response replaces the whole
  // panel, which unmounts this root and mounts the new one.
  const values = {
    app: panel.app,
    instance_id: panel.instance_id,
    kind: panel.search.kind,
    arr_id: panel.search.arr_id,
  };
  if (panel.search.season != null) values.season = panel.search.season;
  if (props.seasonNumber != null) values.season_number = props.seasonNumber;
  if (props.episodeNumber != null) values.episode_number = props.episodeNumber;
  window.htmx.ajax('POST', props.panelUrl, {
    target: host.closest('.library-panel'),
    swap: 'outerHTML',
    values,
  });
}

export function mountIntegrationPanels(host, props) {
  return mountRoot(host, <ArrLibraryPanels
    panels={props.panels}
    message={props.message}
    error={props.error}
    seerrRequests={props.seerrRequests ?? undefined}
    seerrError={props.seerrError}
    seerrUrl={props.seerrUrl}
    labels={props.labels}
    palette={palette}
    variant="web"
    linkProps={linkProps}
    onCopy={copyText}
    onSearch={panel => startSearch(host, props, panel)} />);
}
