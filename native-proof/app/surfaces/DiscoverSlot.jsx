import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

export const surface = {
  id: 'DISCOVER',
  title: 'Discover rows, tabs and feedback',
  where: 'Discover',
  status: 'in_progress',
  note: 'The shared tabs, recommendation rows, hidden grid, feedback states and RSS row preview are being ported.',
};

export default function DiscoverSlot() {
  return <Screen title="Discover" subtitle="Recommendations for the media types you follow">
    <Note surface={surface} />
  </Screen>;
}
