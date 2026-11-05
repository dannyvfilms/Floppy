import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'WEB-UTILITIES',
  title: 'Clipboard and install',
  where: 'Copy controls, install feedback and static cache',
  status: 'in_progress',
  note: 'Copy intents, install prompts and service-worker status will replace this note where they have a native equivalent.',
};

export default function WebUtilitiesScreen({ onBack }) {
  return <Screen title="Clipboard" subtitle="Clipboard and install" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
