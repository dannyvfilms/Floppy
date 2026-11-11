import React from 'react';
import { SearchPageView } from '../../../frontend/pages/SearchPageView';
import { Screen } from '../components/Screen';
import SearchResultsSlot from '../surfaces/SearchResultsSlot';

// The shell already carries the search field and, on the Duo, the back button, so this screen
// is only the results: no second search bar and no Back link of its own.
export default function SearchScreen({ params, navigate }) {
  return <Screen chrome={false}>
    <SearchPageView
      results={<SearchResultsSlot
        query={params?.query || ''}
        mediaType={params?.mediaType || 'all'}
        onOpenDetail={card => navigate('Detail', { item: card })}
      />}
    />
  </Screen>;
}
