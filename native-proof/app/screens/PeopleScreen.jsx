import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'PEOPLE',
  title: 'People, studios and credits',
  where: 'Person, studio and cast detail',
  note: 'Person/studio pages, credits, filmography, trailers and game extras will replace this note.',
};

export default function PeopleScreen({ onBack }) {
  return <Screen title="People, studios" subtitle="People, studios and credits" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
