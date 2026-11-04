import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-PREFERENCES',
  title: 'Preferences and save states',
  where: 'Settings preferences',
  status: 'in_progress',
  note: 'The preference fields, selected/disabled/error states and dirty save bar are being ported to the shared React Native controls.',
};

export default function PreferencesSlot() {
  return <Note surface={surface} />;
}
