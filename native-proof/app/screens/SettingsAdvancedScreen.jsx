import React from 'react';
import { Screen } from '../components/Screen';
import AboutSettingsSlot from '../surfaces/AboutSettingsSlot';
import AdvancedSettingsSlot from '../surfaces/AdvancedSettingsSlot';

export const surface = {
  id: 'SET-SYSTEM-SCREEN',
  title: 'Advanced and About',
  where: 'System, updates, logs and API links',
  status: 'in_progress',
  note: 'Thin route wrapper: the Settings navigation renders the Advanced and About slots inside the settings shell; this screen keeps the SettingsAdvanced route working for callers that navigate to it directly. Data and actions live in the slots and /api/v1/user/advanced/ and /api/v1/user/about/.',
};

export default function SettingsAdvancedScreen({ onBack, params }) {
  return <Screen onBack={onBack}>
    {params?.page === 'about' ? <AboutSettingsSlot /> : <AdvancedSettingsSlot />}
  </Screen>;
}
