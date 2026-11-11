import React from 'react';
import { Screen } from '../components/Screen';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { useDiscoverSurface } from '../surfaces/DiscoverSlot';

// Native adapter for the shared Discover composition. It supplies the search
// slot, demo/server candidates and navigation intents; DiscoverView owns the
// heading, toolbar, tabs, feedback, rows/hidden order and states.
// The web page body starts 24px below the header.
const pageTop = { paddingTop: 24 };

export default function DiscoverScreen({ navigate }) {
  const surface = useDiscoverSurface({ navigate });
  return <Screen chrome={false} contentStyle={pageTop}>
    <DiscoverView {...surface} />
  </Screen>;
}
