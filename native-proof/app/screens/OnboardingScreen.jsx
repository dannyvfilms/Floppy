import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'ONBOARDING',
  title: 'Onboarding',
  where: 'First-run media, metadata, services and connection steps',
  note: 'The resumable onboarding wizard and connection/import variants will replace this note.',
};

export default function OnboardingScreen({ onBack }) {
  return <Screen title="Onboarding" subtitle="Onboarding" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
