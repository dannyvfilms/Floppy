import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SEARCH',
  title: 'Global search and suggestions',
  where: 'Header on Home, Discover and Library',
  note: 'The search field, media-type menu and suggestion list will open the Search screen and result detail routes.',
};

export default function SearchSlot() {
  return <Note surface={surface} compact />;
}
