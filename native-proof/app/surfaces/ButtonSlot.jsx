import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'BUTTON',
  title: 'Primary, surface and danger actions',
  where: 'Save bars, Load more, provider actions and confirmations',
  status: 'in_progress',
  note: 'The shared action button is being migrated to universal presentation and will replace this note with the focused, busy and disabled action primitive.',
};

export default function ButtonSlot() {
  return <Note surface={surface} compact />;
}
