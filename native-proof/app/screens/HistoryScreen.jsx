import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';

const history = {
  id: 'HISTORY',
  status: 'in_progress',
  title: 'History feed and activity',
  where: 'History screen and per-item activity dialog',
  note: 'Bounded day groups, edits, deletes and session history will replace this note.',
};

export default function HistoryScreen({ onBack }) {
  return <Screen title="History" subtitle="Everything you have watched, read and played" onBack={onBack}>
    <Section title="Recent days"><Note surface={history} /></Section>
  </Screen>;
}
