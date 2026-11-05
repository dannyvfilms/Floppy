import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

export const surface = {
  id: 'INTEGRATION-PANELS',
  status: 'in_progress',
  title: 'Library and request panels',
  where: 'Detail Arr/Seerr status and request actions',
  note: 'Library availability, Seerr requests, season/episode controls and provider errors will replace this note.',
};

export default function IntegrationsScreen({ onBack }) {
  return <Screen title="Library" subtitle="Library and request panels" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
