import React from 'react';
import App from '../../App';
import RailPreview from './rail-preview';
import SearchPreview from './search-preview';

export default function Index() {
  if (process.env.EXPO_PUBLIC_SEARCH_PREVIEW === '1') return <SearchPreview />;
  return process.env.EXPO_PUBLIC_RAIL_PREVIEW === '1' ? <RailPreview /> : <App />;
}
