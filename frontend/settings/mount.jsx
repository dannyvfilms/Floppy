import React from 'react';
import { SettingsCard } from './SettingsCard';
import { webPalette } from './webPalette';
import { mountRoot } from './root';

export function mountCard(host, props) {
  return mountRoot(host, <SettingsCard {...props} palette={webPalette} framed={false}
      onInfo={props.info_label ? (event) => {
        host.dispatchEvent(new CustomEvent('settings-card:info', {
          bubbles: true, detail: { trigger: event.currentTarget },
        }));
      } : undefined} />);
}
