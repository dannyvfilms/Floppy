import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'RELEASE-CALENDAR',
  title: 'Release calendar',
  where: 'Calendar month, agenda and list views',
  status: 'in_progress',
  note: 'The month grid, agenda, list view, release/status/media/tag filters, toolbar and calendar actions are being ported to the shared calendar component.',
};

export default function CalendarSlot() {
  return <Note surface={surface} />;
}
