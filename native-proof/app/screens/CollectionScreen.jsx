import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'OWNERSHIP',
  title: 'Collection and copies',
  where: 'Collection browser and detail ownership',
  note: 'Ownership grids, copies, labels, custom fields and collection editing will replace this note.',
};

export default function CollectionScreen({ onBack }) {
  return <Screen title="Collection" subtitle="Collection and copies" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
