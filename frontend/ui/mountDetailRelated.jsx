import React from 'react';
import { mountRoot } from '../settings/root';
import { DetailRelatedTheme } from './DetailRelatedTheme.web';

export function mountDetailRelated(host, props) {
  return mountRoot(host, <DetailRelatedTheme host={host} props={props} />);
}
