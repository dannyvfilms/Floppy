import React from 'react';
import { Screen } from '../components/Screen';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { useDiscoverSurface } from '../surfaces/DiscoverSlot';
import SearchSlot from '../surfaces/SearchSlot';

// Native adapter for the shared Discover composition. It supplies the search
// slot, demo/server candidates and navigation intents; DiscoverView owns the
// heading, toolbar, tabs, feedback, rows/hidden order and states.
export default function DiscoverScreen({ navigate }) {
  const surface = useDiscoverSurface({ navigate });
  return <Screen chrome={false}>
    <DiscoverView
      {...surface}
      search={<SearchSlot
        onOpenSearch={params => navigate?.('Search', params)}
        onOpenSuggestion={item => navigate?.('Detail', { item })}
      />}
    />
  </Screen>;
}
