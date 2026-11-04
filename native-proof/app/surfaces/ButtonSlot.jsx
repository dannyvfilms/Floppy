import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'BUTTON',
  title: 'Primary, surface and danger actions',
  where: 'Save bars, Load more, provider actions and confirmations',
  note: 'The shared action button will replace this note and become the focused, busy and disabled action primitive on every screen.',
};

export default function ButtonSlot() {
  return <Note surface={surface} compact />;
}
