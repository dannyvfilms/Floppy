import React from 'react';
import { View } from 'react-native';
import { SearchResultCard as SharedSearchResultCard } from './SearchResultCard';

// Native counterpart for the browser search-result card wrapper.
export function SearchResultCard(props) {
  return <View><SharedSearchResultCard {...props} /></View>;
}
