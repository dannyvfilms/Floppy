import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import RailsSlot from '../surfaces/RailsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export const surface = {
  id: 'HOME',
  status: 'in_progress',
  title: 'Home shelves, deferred groups and cover refresh',
  where: 'Home screen shelves, media-type sections, deferred rows and coalesced artwork polling',
  note: 'Porting Home composition to shared React Native presentation. The native screen still renders demo shelves while the shared composition and transport are wired.',
};

const activity = {
  id: 'HISTORY',
  title: 'Recent activity',
  where: 'Home activity strip and the History screen',
  note: 'Finished plays, episode rows and the activity modal will appear here after the History rows are ported.',
};

export default function HomeScreen({ navigate }) {
  return <Screen title="Home" subtitle="Your next episodes, progress and shelves">
    <SearchSlot
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}
    />
    <Section title="Continue watching" copy="Cards and quick progress in their real Home rail.">
      <MediaCardSlot onOpenDetail={() => navigate('Detail')} />
    </Section>
    <Section title="Next up" copy="Horizontal shelves land here as rails and cards are ported.">
      <RailsSlot />
    </Section>
    <Section title="Recent activity">
      <Note surface={activity} />
    </Section>
  </Screen>;
}
