import React from 'react';
import { mountRoot } from '../settings/root';
import { Spinner } from './SpinnerTheme.web';

export function mountSpinner(host, props) {
  return mountRoot(host, <Spinner {...props} />);
}
