import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'PEOPLE',
  status: 'in_progress',
  title: 'People, studios and credits',
  where: 'Person, studio and cast detail',
  note: 'Person/studio pages, credits, filmography, bounded rails, trailers, lightbox intents and medium extras are being ported to shared React Native presentation. Production transport, permissions and web mounting remain outstanding.',
};

export default function PeopleScreen({ onBack }) {
  return <Screen title="People, studios" subtitle="People, studios and credits" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
