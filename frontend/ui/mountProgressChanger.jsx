import React from 'react';
import { mountRoot } from '../settings/root';
import { ProgressChanger } from './ProgressChangerTheme.web';

export function mountProgressChanger(host, props) {
  return mountRoot(host, <ProgressChanger host={host} props={props} />);
}
