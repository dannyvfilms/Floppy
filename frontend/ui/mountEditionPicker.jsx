import React from 'react';
import { mountRoot } from '../settings/root';
import { EditionPicker } from './ArtworkPicker.web.jsx';

export function mountEditionPicker(host, props) {
  return mountRoot(host, <EditionPicker host={host} props={props} />);
}
