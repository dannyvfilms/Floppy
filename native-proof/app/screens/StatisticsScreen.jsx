import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';

const statistics = {
  id: 'STATISTICS',
  title: 'Statistics dashboard',
  where: 'Statistics, comparison and taste screens',
  note: 'Charts, ranges, highlights and featured repeats will replace this note after a native chart renderer is chosen.',
};

export default function StatisticsScreen({ onBack }) {
  return <Screen title="Statistics" subtitle="Your viewing and reading over time" onBack={onBack}>
    <Section title="Activity"><Note surface={statistics} /></Section>
  </Screen>;
}
