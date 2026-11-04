import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'RAILS',
  title: 'Horizontal shelves and load more',
  where: 'Home rails, Discover, cast and recommendations',
  note: 'The shared rail owns horizontal scrolling, arrows, touch scrolling and bounded load-more once the media card can render items.',
};

export default function RailsSlot() {
  return <Note surface={surface} />;
}
