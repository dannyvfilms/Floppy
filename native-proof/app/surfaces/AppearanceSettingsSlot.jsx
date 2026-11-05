import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-APPEARANCE',
  title: 'Appearance and detail layout editor',
  where: 'Settings appearance theme, custom palette and detail section layout',
  status: 'in_progress',
  note: 'Theme presets, custom palette effects and detail section enable/order are being ported to the shared React Native editor.',
};

export default function AppearanceSettingsSlot() {
  return <Note surface={surface} />;
}
