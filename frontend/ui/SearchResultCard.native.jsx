import React from 'react';
// The explicit extension matters: './SearchResultCard' would resolve back to this native file and loop.
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { SearchResultCard as SharedSearchResultCard } from './SearchResultCard.jsx';

// Native counterpart for the browser search-result card wrapper.
export function SearchResultCard(props) {
  return <SharedSearchResultCard {...props} />;
}
