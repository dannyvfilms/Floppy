import React from 'react';
import { mountRoot } from '../settings/root';
import { ProgressDetailTheme } from './ProgressDetailTheme.web';

export function mountProgressDetail(host, props) {
  return mountRoot(host, <ProgressDetailTheme host={host} props={props} />);
}
