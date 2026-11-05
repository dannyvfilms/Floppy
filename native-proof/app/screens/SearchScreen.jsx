import React, { useState } from 'react';
import { Screen, Section } from '../components/Screen';
import SearchParentSlot from '../surfaces/SearchParentSlot';
import SearchResultsSlot from '../surfaces/SearchResultsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export default function SearchScreen({ params, navigate, onBack }) {
  const [submitted, setSubmitted] = useState(params?.query || 'dune');
  const [mediaType, setMediaType] = useState(params?.mediaType || 'all');
  return <Screen title="Search" subtitle="Find something in your library or online" onBack={onBack}>
    <Section title="Search">
      <SearchSlot
        expanded
        initialQuery={params?.query || submitted}
        initialMediaType={params?.mediaType || mediaType}
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
    <Section title="Create entry parents" copy="Choose the parent record when adding a season, episode or track.">
      <SearchParentSlot />
    </Section>
  </Screen>;
}
