import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-HOME',
  title: 'Home screen shelf editor',
  where: 'Settings home screen sections, rows, filters, sort and order',
  status: 'in_progress',
  note: 'Home sections, shelves, filters, sorting and ordering are being ported to the shared React Native editor.',
};

export default function HomeSettingsSlot() {
  return <Note surface={surface} />;
}
