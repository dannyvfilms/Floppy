import React, { useEffect, useState } from 'react';
import App from '../../App';
import { subscribeTheme } from '../themeState';
import RailPreview from './rail-preview';
import SearchPreview from './search-preview';

export default function Index() {
  // A theme change re-renders the whole app in place (new element, same
  // component instance), so navigation state is kept.
  const [, setVersion] = useState(0);
  useEffect(() => subscribeTheme(() => setVersion(count => count + 1)), []);
  if (process.env.EXPO_PUBLIC_SEARCH_PREVIEW === '1') return <SearchPreview />;
  return process.env.EXPO_PUBLIC_RAIL_PREVIEW === '1' ? <RailPreview /> : <App />;
}
