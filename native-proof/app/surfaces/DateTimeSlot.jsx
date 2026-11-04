import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'DATE-TIME',
  status: 'in_progress',
  title: 'Tracking date and time picker',
  where: 'Tracking dialogs and History date ranges',
  note: 'The universal date/time field is being ported; the web picker remains Alpine-owned until its adapter is ready.',
};

export default function DateTimeSlot() {
  return <Note surface={surface} />;
}
