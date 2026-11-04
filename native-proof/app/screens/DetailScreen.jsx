import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import ProgressSlot from '../surfaces/ProgressSlot';
import RatingSlot from '../surfaces/RatingSlot';

const detail = {
  id: 'DETAIL',
  status: 'in_progress',
  title: 'Detail composition and metadata',
  where: 'Film, show, game, book, music and podcast detail pages',
  note: 'Artwork, title facts, synopsis, sections and actions will replace this note. The shared rating input below is already in its detail position.',
};
const children = {
  id: 'CHILDREN',
  title: 'Seasons, episodes and issue rows',
  where: 'Show, season, podcast and comic detail pages',
  note: 'Episode and issue rows, watched controls and history links will replace this note.',
};

export default function DetailScreen({ params, onBack }) {
  const title = params?.item?.title || 'Detail';
  return <Screen title={title} subtitle="Detail, tracking and rating" onBack={onBack}>
    <Section title="Metadata">
      <Note surface={detail} />
    </Section>
    <Section title="Your score">
      <RatingSlot />
    </Section>
    <Section title="Your progress">
      <ProgressSlot />
    </Section>
    <Section title="Episodes and issues">
      <Note surface={children} />
    </Section>
  </Screen>;
}
