import React from 'react';
import { mountRoot } from '../settings/root';
import { SearchPageView } from '../pages/SearchPageView';
import { SearchResults } from './SearchResults.web.jsx';

// The web adapter supplies only the shared SearchResults surface; the native
// screen supplies its search field and result transport. Page order and the
// result states stay in the shared composition.
export function mountSearchResults(host, props) {
  return mountRoot(host, <SearchPageView
    results={<SearchResults props={props} />} />);
}
