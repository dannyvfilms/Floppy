import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'SET-SYSTEM',
  title: 'Advanced and About',
  where: 'System, updates, logs, install and API links',
  note: 'Cache/image controls, confirmations, release info, install/API links and port restrictions will replace this note.',
};

export default function SettingsAdvancedScreen({ onBack }) {
  return <Screen title="Advanced" subtitle="Advanced and About" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
