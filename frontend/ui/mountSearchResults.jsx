import React from 'react';
import { mountRoot } from '../settings/root';
import { SearchResults } from './SearchResults.web.jsx';

export function mountSearchResults(host, props) {
  return mountRoot(host, <SearchResults props={props} />);
}
