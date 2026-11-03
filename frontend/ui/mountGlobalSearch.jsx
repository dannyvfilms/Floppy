import React from 'react';
import { mountRoot } from '../settings/root';
import { GlobalSearch } from './GlobalSearch';

export function mountGlobalSearch(host, props) {
  return mountRoot(host, <GlobalSearch props={props} />);
}
