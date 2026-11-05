import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-DATA',
  title: 'Data, access and notification settings',
  where: 'Settings data export, RSS, access tokens, OAuth grants and notifications',
  status: 'in_progress',
  note: 'Data export and restore, RSS feeds, access tokens and grants, and notification preferences are being ported to shared React Native presentation.',
};

export default function DataAccessNotificationsSlot() {
  return <Note surface={surface} />;
}
