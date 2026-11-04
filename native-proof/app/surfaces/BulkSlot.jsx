import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'BULK',
  title: 'Bulk selection and actions',
  where: 'Library, custom lists and smart lists',
  status: 'in_progress',
  note: 'Select mode, card selection, the selected count, Library and History toolbar actions, confirmations, busy and partial-failure states and clear/reset are being ported to shared bulk presentation.',
};

export default function BulkSlot() {
  return <Note surface={surface} />;
}
