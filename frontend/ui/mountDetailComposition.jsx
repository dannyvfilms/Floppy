import React from 'react';
import { mountRoot } from '../settings/root';
import { DetailCompositionTheme } from './DetailCompositionTheme.web';

export function mountDetailComposition(host, props) {
  return mountRoot(host, <DetailCompositionTheme host={host} props={props} />);
}
