import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'DETAIL-RELATED',
  status: 'in_progress',
  title: 'Related media and Steam DLCs',
  where: 'Game, movie, show, book and comic detail pages',
  note: 'IGDB DLC, expansion and remake cards plus display-only Steam DLC links are moving to the shared React Native presentation.',
};

export default function DetailRelatedSlot() {
  return <Note surface={surface} />;
}
