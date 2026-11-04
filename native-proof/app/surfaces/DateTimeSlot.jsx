import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'DATE-TIME',
  title: 'Tracking date and time picker',
  where: 'Tracking dialogs and History date ranges',
  note: 'The native date/time picker will replace this note when tracking forms are ported.',
};

export default function DateTimeSlot() {
  return <Note surface={surface} />;
}
