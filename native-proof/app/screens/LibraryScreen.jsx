import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import BulkSlot from '../surfaces/BulkSlot';
import ButtonSlot from '../surfaces/ButtonSlot';
import FiltersSlot from '../surfaces/FiltersSlot';
import SearchSlot from '../surfaces/SearchSlot';

const tables = {
  id: 'TABLES',
  title: 'Table view and columns',
  where: 'Library and list table layouts',
  status: 'in_progress',
  note: 'The configurable table, column menu and row cells will replace the card notes for table mode.',
};

export default function LibraryScreen({ navigate }) {
  return <Screen title="Library" subtitle="Everything you track, filtered the way you left it">
    <SearchSlot
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}
    />
    <FiltersSlot />
    <Section title="Movies and shows">
      <BulkSlot onOpenDetail={() => navigate('Detail')} />
    </Section>
    <Section title="Table view">
      <Note surface={tables} />
    </Section>
    <ButtonSlot />
  </Screen>;
}
