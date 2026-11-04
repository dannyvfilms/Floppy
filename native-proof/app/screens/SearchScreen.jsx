import React, { useState } from 'react';
import { Screen, Section } from '../components/Screen';
import SearchResultsSlot from '../surfaces/SearchResultsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export default function SearchScreen({ params, navigate, onBack }) {
  const [submitted, setSubmitted] = useState(params?.query || 'dune');
  const [mediaType, setMediaType] = useState(params?.mediaType || 'all');
  return <Screen title="Search" subtitle="Find something in your library or online" onBack={onBack}>
    <Section title="Search">
      <SearchSlot
        expanded
        initialQuery={params?.query}
        initialMediaType={params?.mediaType}
        onSubmit={({ query, mediaType: nextType }) => {
          setSubmitted(query);
          if (nextType) setMediaType(nextType);
        }}
        onOpenSuggestion={suggestion => navigate('Detail', { item: suggestion })}
      />
    </Section>
    <Section title="Results">
      <SearchResultsSlot
        query={submitted}
        mediaType={mediaType}
        onOpenDetail={() => navigate('Detail')}
      />
    </Section>
  </Screen>;
}
