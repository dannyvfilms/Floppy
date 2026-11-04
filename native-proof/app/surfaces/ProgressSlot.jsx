import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'PROGRESS',
  status: 'in_progress',
  title: 'Detail progress card and breakdown',
  where: 'Show and season detail pages',
  note: 'The “Your Progress” card, season breakdown and rewatch controls will replace this note. The quick Home progress controls are already ported.',
};

export default function ProgressSlot() {
  return <Note surface={surface} />;
}
