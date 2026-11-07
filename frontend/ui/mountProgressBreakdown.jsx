import React from 'react';
import { mountRoot } from '../settings/root';
import { ProgressBreakdownTheme } from './ProgressBreakdownTheme.web';

export function mountProgressBreakdown(host, props) {
  return mountRoot(host, <ProgressBreakdownTheme host={host} props={props} />);
}
