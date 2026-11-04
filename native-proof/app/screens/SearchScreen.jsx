import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import SearchSlot from '../surfaces/SearchSlot';

const results = {
  id: 'SEARCH',
  title: 'Search results',
  where: 'Search screen and parent media pickers',
  note: 'Matched titles, online results, barcode input and paging will replace this note once the search data contract is ported.',
};

export default function SearchScreen({ onBack }) {
  return <Screen title="Search" subtitle="Find something in your library or online" onBack={onBack}>
    <Section title="Search">
      <SearchSlot expanded />
    </Section>
    <Section title="Results">
      <Note surface={results} />
    </Section>
  </Screen>;
}
