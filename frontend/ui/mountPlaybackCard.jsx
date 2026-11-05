import React from 'react';
import { mountRoot } from '../settings/root';
import { PlaybackCardTheme } from './PlaybackTheme.web';

export function mountPlaybackCard(host, props) {
  return mountRoot(host, <PlaybackCardTheme host={host} props={props} />);
}
