import React, { useState } from 'react';
import { SearchPageView } from '../../../frontend/pages/SearchPageView';
import { Screen } from '../components/Screen';
import SearchResultsSlot from '../surfaces/SearchResultsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export default function SearchScreen({ params, navigate, onBack }) {
  const [submitted, setSubmitted] = useState(params?.query || 'dune');
  const [mediaType, setMediaType] = useState(params?.mediaType || 'all');
  return <Screen onBack={onBack}>
    <SearchPageView
      search={<SearchSlot
        expanded
        initialQuery={params?.query || submitted}
        initialMediaType={params?.mediaType || mediaType}
        onSubmit={({ query, mediaType: nextType }) => {
          setSubmitted(query);
          if (nextType) setMediaType(nextType);
        }}
        onOpenSuggestion={suggestion => navigate('Detail', { item: suggestion })}
      />}
      results={<SearchResultsSlot
        query={submitted}
        mediaType={mediaType}
        onOpenDetail={() => navigate('Detail')}
      />}
    />
  </Screen>;
}
