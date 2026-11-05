import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'ERRORS-DOCS',
  title: 'Errors and API docs',
  where: '400/403/404/500 and API documentation',
  note: 'Error recovery/report panels and the API explorer will replace this note.',
};

export default function ErrorDocsScreen({ onBack }) {
  return <Screen title="Errors" subtitle="Errors and API docs" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
