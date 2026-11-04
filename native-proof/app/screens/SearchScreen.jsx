import React, { useState } from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import SearchSlot from '../surfaces/SearchSlot';

const results = {
  id: 'SEARCH',
  title: 'Search results',
  where: 'Search screen and parent media pickers',
  note: 'Matched titles, online results, barcode input and paging will replace this note once the search data contract is ported.',
};

export default function SearchScreen({ params, navigate, onBack }) {
  const [submitted, setSubmitted] = useState(params?.query || '');
  const all = params?.mediaType === 'all' || !params?.mediaType;
  return <Screen title="Search" subtitle="Find something in your library or online" onBack={onBack}>
    <Section title="Search">
      <SearchSlot
        expanded
        initialQuery={params?.query}
        initialMediaType={params?.mediaType}
        onSubmit={({ query }) => setSubmitted(query)}
        onOpenSuggestion={suggestion => navigate('Detail', { item: suggestion })}
      />
    </Section>
    <Section title="Results">
      <Note surface={{
        ...results,
        note: submitted
          ? `Results for “${submitted}” across ${all ? 'every enabled media type' : params.mediaType} will replace this note once the results area is ported.`
          : results.note,
      }} />
    </Section>
  </Screen>;
}
