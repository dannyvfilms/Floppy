import React from 'react';
import { Screen } from '../components/Screen';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { useDiscoverSurface } from '../surfaces/DiscoverSlot';

// Native adapter for the shared Discover composition. It supplies the search
// slot, demo/server candidates and navigation intents; DiscoverView owns the
// heading, toolbar, tabs, feedback, rows/hidden order and states.
export default function DiscoverScreen({ navigate }) {
  const surface = useDiscoverSurface({ navigate });
  return <Screen chrome={false}>
    <DiscoverView {...surface} />
  </Screen>;
}
