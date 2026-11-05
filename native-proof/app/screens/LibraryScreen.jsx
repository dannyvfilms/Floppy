import React from 'react';
import { Screen, Section } from '../components/Screen';
import BulkSlot from '../surfaces/BulkSlot';
import ButtonSlot from '../surfaces/ButtonSlot';
import FiltersSlot from '../surfaces/FiltersSlot';
import SearchSlot from '../surfaces/SearchSlot';
import TableSlot from '../surfaces/TableSlot';

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
      <TableSlot onOpenDetail={() => navigate('Detail')} />
    </Section>
    <ButtonSlot />
  </Screen>;
}
