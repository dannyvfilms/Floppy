import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import DetailSlot from '../surfaces/DetailSlot';
import ProgressSlot from '../surfaces/ProgressSlot';
import RatingSlot from '../surfaces/RatingSlot';

const children = {
  id: 'CHILDREN',
  title: 'Seasons, episodes and issue rows',
  where: 'Show, season, podcast and comic detail pages',
  note: 'Episode and issue rows, watched controls and history links will replace this note.',
};

export default function DetailScreen({ params, onBack }) {
  const title = params?.item?.title || 'Detail';
  return <Screen title={title} subtitle="Detail, tracking and rating" onBack={onBack}>
    <DetailSlot />
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
