import React from 'react';
import { mountRoot } from '../settings/root';
import { setupGuideProps } from './ProviderSettingsView';
import { SetupGuide } from '../ui/SetupGuide';
import { copyText, readThemePalette } from './transport.web';

export function mountSetupGuide(host, guide) {
  const copy = Object.fromEntries(
    [...host.querySelectorAll('input[data-copy-id]')].map(input => [input.dataset.copyId, input.value]),
  );
  return mountRoot(host, <SetupGuide
    {...setupGuideProps(guide, copy, guide.labels)}
    palette={readThemePalette()}
    onCopy={copyText}
    onOpenLink={(url, label) => { if (url) window.open(url, '_blank', 'noopener'); void label; }}
  />);
}
