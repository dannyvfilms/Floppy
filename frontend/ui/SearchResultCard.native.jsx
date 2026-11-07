import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { SearchResultCard as SharedSearchResultCard } from './SearchResultCard';

// Native counterpart for the browser search-result card wrapper.
export function SearchResultCard(props) {
  return <SharedSearchResultCard {...props} />;
}
