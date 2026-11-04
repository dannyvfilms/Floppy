import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'FILTERS',
  title: 'Filter toolbar and saved views',
  where: 'Library, lists, History and Calendar',
  note: 'Media type, status, sort, saved-view and range controls will sit above the result grid.',
};

export default function FiltersSlot() {
  return <Note surface={surface} />;
}
