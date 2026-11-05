import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'TAGS',
  status: 'in_progress',
  title: 'Tags',
  where: 'Tag index and assignment',
  note: 'Tag search, assignment, bulk tagging and library-wide deletion will replace this note.',
};

export default function TagsScreen({ onBack }) {
  return <Screen title="Tags" subtitle="Tags" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
