import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-PROVIDERS',
  title: 'Provider Connection and Import settings',
  where: 'Settings provider connection, import and setup guide',
  status: 'in_progress',
  note: 'The provider credential, account, import and setup-guide forms are being ported to shared React Native controls.',
};

export default function ProviderSettingsSlot() {
  return <Note surface={surface} />;
}
