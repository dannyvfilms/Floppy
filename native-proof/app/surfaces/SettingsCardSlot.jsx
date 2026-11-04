import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SETTINGS-CARD',
  title: 'Settings card and chip',
  where: 'Settings, provider Connection, Import and Activity',
  status: 'in_progress',
  note: 'The shared card heading, info chip and body layout will replace this note on settings and provider screens.',
};

export default function SettingsCardSlot() {
  return <Note surface={surface} />;
}
