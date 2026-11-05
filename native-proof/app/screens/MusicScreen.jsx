import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'MUSIC',
  title: 'Music and podcasts',
  where: 'Artist, album, track and podcast detail',
  note: 'Artist relations, discography, album tracks, show episodes and podcast tracking will replace this note.',
};

export default function MusicScreen({ onBack }) {
  return <Screen title="Music" subtitle="Music and podcasts" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
