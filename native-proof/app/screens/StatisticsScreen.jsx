import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';

const statistics = {
  id: 'STATISTICS',
  title: 'Statistics dashboard',
  where: 'Statistics, comparison and taste screens',
  status: 'in_progress',
  note: 'The summary cards, activity overview, highlights, states and range/media-type controls are being ported; chart canvases and the comparison/taste views remain legacy.',
};

export default function StatisticsScreen({ onBack }) {
  return <Screen title="Statistics" subtitle="Your viewing and reading over time" onBack={onBack}>
    <Section title="Activity"><Note surface={statistics} /></Section>
  </Screen>;
}
