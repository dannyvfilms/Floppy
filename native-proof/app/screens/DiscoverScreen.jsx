import React from 'react';
import { Screen, Section } from '../components/Screen';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import RailsSlot from '../surfaces/RailsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export default function DiscoverScreen({ navigate }) {
  return <Screen title="Discover" subtitle="Recommendations for the media types you follow">
    <SearchSlot
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}
    />
    <Section title="Recommended for you">
      <MediaCardSlot onOpenDetail={() => navigate('Detail')} />
    </Section>
    <Section title="More rows">
      <RailsSlot />
    </Section>
  </Screen>;
}
