import React from 'react';
import { mountRoot } from '../settings/root';
import { CheckInStateTheme } from './PlaybackTheme.web';

export function mountCheckInState(host, props) {
  return mountRoot(host, <CheckInStateTheme host={host} props={props} />);
}
