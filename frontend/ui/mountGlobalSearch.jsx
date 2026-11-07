import React from 'react';
import { mountRoot } from '../settings/root';
import { GlobalSearch } from './GlobalSearch.web';

export function mountGlobalSearch(host, props) {
  return mountRoot(host, <GlobalSearch host={host} props={props} />);
}
