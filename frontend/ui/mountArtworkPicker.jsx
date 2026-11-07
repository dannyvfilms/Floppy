import React from 'react';
import { mountRoot } from '../settings/root';
import { ArtworkPicker } from './ArtworkPicker.web.jsx';

export function mountArtworkPicker(host, props) {
  return mountRoot(host, <ArtworkPicker host={host} props={props} />);
}
