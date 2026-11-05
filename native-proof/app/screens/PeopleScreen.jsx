import React, { useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { Rail } from '../../../frontend/ui/Rail';
import {
  CreditCard,
  LightboxDialog,
  MediaGallery,
  MediumExtras,
  PersonCard,
  PersonHero,
  StudioHero,
} from '../../../frontend/ui/People';
import { Note } from '../components/Note';
import { Screen, Section } from '../components/Screen';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'PEOPLE',
  status: 'in_progress',
  title: 'People, studios and credits',
  where: 'Person and studio pages, cast/filmography/credit rows, trailers, lightbox and medium extras',
  note: 'Person and studio pages, cast and credit cards with role lines, bounded rails, a trailer/photo gallery with play and lightbox intents, and time-to-beat, YouTube and reading extras render with shared React Native presentation and demo data. Production data transport, permissions, web mounting and iOS/Android runtime verification remain outstanding.',
};

const DEMO_PERSON = {
  id: 'nora-voss',
  name: 'Nora Voss',
  imageUrl: 'https://picsum.photos/seed/floppy-person-nora/500/750',
  knownForDepartment: 'Acting',
  biography:
    'Nora Voss is a stage and screen actor known for restrained, watchful performances in coastal dramas. She trained in Halifax and spent a decade in regional theatre before moving into television, where her work on Signal Fires made her a familiar face in slow-burn mystery series. Off screen she directs short documentaries about working harbours.',
  birthDate: 'Mar 14, 1986',
  placeOfBirth: 'Halifax, Nova Scotia',
  sourceLabel: 'TMDB',
  sourceUrl: 'https://www.themoviedb.org/person/1001',
  isAuthor: false,
};

const PERSON_COUNTS = [
  { label: '2 movies' },
  { label: '2 shows' },
  { label: '9 tracked plays' },
  { label: '31h 20m' },
];

const WATCHED_CREDITS = [
  {
    id: 'lantern-coast',
    title: 'The Lantern Coast',
    mediaTypeLabel: 'Movie',
    mediaType: 'movie',
    year: 2024,
    role: 'Mara Vell',
    imageUrl: 'https://picsum.photos/seed/floppy-lantern/400/600',
    watchedRuntimeLabel: '1h 58m tracked',
    watched: true,
  },
  {
    id: 'signal-fires',
    title: 'Signal Fires',
    mediaTypeLabel: 'TV Show',
    mediaType: 'tv',
    year: 2023,
    role: 'Det. Iona Reyes',
    imageUrl: 'https://picsum.photos/seed/floppy-signal/400/600',
    watchedRuntimeLabel: '6h 40m tracked',
    watched: true,
  },
];

const FILMOGRAPHY = [
  ...WATCHED_CREDITS,
  {
    id: 'glass-harbour',
    title: 'Glass Harbour',
    mediaTypeLabel: 'Movie',
    mediaType: 'movie',
    year: 2021,
    role: 'Dr. Elin Sorkin',
    imageUrl: 'https://picsum.photos/seed/floppy-glass/400/600',
    voteAverage: 7.6,
  },
  {
    id: 'quiet-atlas',
    title: 'The Quiet Atlas',
    mediaTypeLabel: 'TV Show',
    mediaType: 'tv',
    year: 2020,
    role: 'Narrator',
    imageUrl: 'https://picsum.photos/seed/floppy-atlas/400/600',
    voteAverage: 8.2,
  },
  {
    id: 'northbound',
    title: 'Northbound',
    mediaTypeLabel: 'Movie',
    mediaType: 'movie',
    year: 2019,
    role: 'Captain Ines Rook',
    imageUrl: 'https://picsum.photos/seed/floppy-northbound/400/600',
    voteAverage: 7.1,
  },
  {
    id: 'tidewater',
    title: 'Tidewater',
    mediaTypeLabel: 'TV Show',
    mediaType: 'tv',
    year: 2017,
    role: 'Sonya Bell',
    imageUrl: 'https://picsum.photos/seed/floppy-tidewater/400/600',
    voteAverage: 6.9,
  },
];

const CAST = [
  { id: 'nora', name: 'Nora Voss', subtitle: 'Det. Iona Reyes', episodeCount: 18,
    imageUrl: 'https://picsum.photos/seed/floppy-person-nora/300/450' },
  { id: 'eli', name: 'Eli Mercer', subtitle: 'Chief Arlo Dane · 12 eps', episodeCount: 12,
    imageUrl: 'https://picsum.photos/seed/floppy-person-eli/300/450' },
  { id: 'mira', name: 'Mira Adeyemi', subtitle: 'Dr. Sena Okafor · 10 eps', episodeCount: 10,
    imageUrl: 'https://picsum.photos/seed/floppy-person-mira/300/450' },
  { id: 'tomas', name: 'Tomás Ibarra', subtitle: 'Rafael Quill · 8 eps', episodeCount: 8,
    imageUrl: 'https://picsum.photos/seed/floppy-person-tomas/300/450' },
  { id: 'june', name: 'June Park', subtitle: 'Lena Hsu · 6 eps', episodeCount: 6,
    imageUrl: 'https://picsum.photos/seed/floppy-person-june/300/450' },
];

const DEMO_STUDIO = {
  id: 'northlight',
  name: 'Northlight Interactive',
  logoUrl: 'https://picsum.photos/seed/floppy-studio-northlight/500/500',
  description:
    'Northlight Interactive is an independent studio building atmospheric exploration games from a converted warehouse on the Tyne. The team is known for hand-painted environments, patient pacing and scores recorded with local musicians.',
  founded: '2011',
  mediaLabel: 'Games',
  titleCount: 12,
  developedCount: 9,
  publishedCount: 5,
  sourceLabel: 'IGDB',
  sourceUrl: 'https://www.igdb.com/companies/northlight-interactive',
  websiteUrl: 'https://example.com/northlight',
};

const STUDIO_COUNTS = [
  { label: '12 games' },
  { label: '9 developed' },
  { label: '5 published' },
];

const STUDIO_TITLES = [
  { id: 'harbour-lights', title: 'Harbour Lights', mediaTypeLabel: 'Game', year: 2025,
    role: 'Developer, Publisher', imageUrl: 'https://picsum.photos/seed/floppy-harbour-lights/400/600',
    watchedRuntimeLabel: '12h tracked', watched: true },
  { id: 'salt-and-iron', title: 'Salt & Iron', mediaTypeLabel: 'Game', year: 2024,
    role: 'Developer', imageUrl: 'https://picsum.photos/seed/floppy-salt-iron/400/600', voteAverage: 8.4 },
  { id: 'north-sea-radio', title: 'North Sea Radio', mediaTypeLabel: 'Game', year: 2023,
    role: 'Developer, Publisher', imageUrl: 'https://picsum.photos/seed/floppy-radio/400/600', voteAverage: 7.9 },
  { id: 'the-long-wake', title: 'The Long Wake', mediaTypeLabel: 'Game', year: 2022,
    role: 'Developer', imageUrl: 'https://picsum.photos/seed/floppy-long-wake/400/600', voteAverage: 8.1 },
  { id: 'tidal-lock', title: 'Tidal Lock', mediaTypeLabel: 'Game', year: 2020,
    role: 'Publisher', imageUrl: 'https://picsum.photos/seed/floppy-tidal-lock/400/600', voteAverage: 7.4 },
  { id: 'lantern-keepers', title: 'Lantern Keepers', mediaTypeLabel: 'Game', year: 2018,
    role: 'Developer', imageUrl: 'https://picsum.photos/seed/floppy-lantern-keepers/400/600', voteAverage: 7.8 },
];

const GALLERY = [
  { id: 'overview', kind: 'overview', label: 'Overview',
    url: 'https://picsum.photos/seed/floppy-gallery-overview/1280/720',
    thumbUrl: 'https://picsum.photos/seed/floppy-gallery-overview/320/180' },
  { id: 'trailer', kind: 'video', key: 'dQw4w9WgXcQ', label: 'Season trailer',
    posterUrl: 'https://picsum.photos/seed/floppy-gallery-trailer/1280/720',
    thumbUrl: 'https://picsum.photos/seed/floppy-gallery-trailer/320/180' },
  { id: 'harbour', kind: 'image', label: 'Harbour at dusk',
    url: 'https://picsum.photos/seed/floppy-gallery-harbour/1280/720',
    thumbUrl: 'https://picsum.photos/seed/floppy-gallery-harbour/320/180' },
  { id: 'signal-room', kind: 'image', label: 'The signal room',
    url: 'https://picsum.photos/seed/floppy-gallery-signal/1280/720',
    thumbUrl: 'https://picsum.photos/seed/floppy-gallery-signal/320/180' },
];

const GAME_LENGTHS = {
  sourceLabel: 'HowLongToBeat',
  sourceUrl: 'https://howlongtobeat.com/game/1001',
  available: true,
  cards: [
    { label: 'Main Story', value: '9h 30m', count: 1240, glyph: '◎' },
    { label: 'Main + Extras', value: '14h 10m', count: 860, glyph: '◈' },
    { label: 'Completionist', value: '23h 45m', count: 310, glyph: '◇' },
    { label: 'All Styles', value: '13h 20m', count: 2410, glyph: '◷' },
  ],
};

const YOUTUBE_WATCH = { seconds: 4080, hoursLabel: '1h 8m', videos: 4 };

const READING = {
  listening: '12h 05m',
  topItems: [
    { id: 'quiet-atlas', title: 'The Quiet Atlas', units: '340 pages' },
    { id: 'glass-harbour', title: 'Glass Harbour: A Field Guide', units: '128 pages' },
  ],
  topAuthors: [
    { id: 'nora', name: 'Nora Voss', units: '2 reads' },
    { id: 'eli', name: 'Eli Mercer', units: '1 read' },
  ],
};

function openExternal(url) {
  if (!url) return;
  Linking.openURL(url).catch(() => {});
}

function Menu({ value, onChange }) {
  const options = [
    { value: 'person', label: 'Person' },
    { value: 'studio', label: 'Studio' },
    { value: 'extras', label: 'Detail extras' },
  ];
  return <View style={styles.menu}>
    {options.map(option => {
      const active = option.value === value;
      return <Pressable key={option.value} accessibilityRole="button" accessibilityLabel={option.label}
        accessibilityState={{ selected: active }} onPress={() => onChange(option.value)}
        style={[styles.menuItem, {
          backgroundColor: active ? palette.accentStrong : palette.surface,
          borderColor: active ? palette.accentStrong : palette.border,
        }]}>
        <Text style={[styles.menuText, { color: active ? '#ffffff' : palette.textSecondary }]}>{option.label}</Text>
      </Pressable>;
    })}
  </View>;
}

export default function PeopleScreen({ navigate, onBack }) {
  const [view, setView] = useState('person');
  const [lightbox, setLightbox] = useState({ visible: false, index: 0 });

  function openCredit(entry) {
    navigate?.('Detail', { item: { title: entry.title, mediaType: entry.mediaType } });
  }

  function openPerson(person) {
    navigate?.('Detail', { item: { title: person.name } });
  }

  return <Screen title="People, studios" subtitle="People, studios and credits" onBack={onBack}>
    <Menu value={view} onChange={setView} />

    {view === 'person' ? <>
      <PersonHero person={DEMO_PERSON} counts={PERSON_COUNTS}
        onViewHistory={() => navigate?.('History')}
        onOpenSource={openExternal} />

      <Rail items={WATCHED_CREDITS} renderItem={entry => <CreditCard entry={entry} onOpen={openCredit} />}
        title="Watched Content" summary={`${WATCHED_CREDITS.length} titles`} itemWidth={176}
        emptyLabel="No watched titles yet." />

      <Rail items={FILMOGRAPHY} renderItem={entry => <CreditCard entry={entry} onOpen={openCredit} />}
        title="Filmography" summary={`${FILMOGRAPHY.length} titles`} summaryInline="Most recent"
        itemWidth={176} emptyLabel="No filmography available." />

      <Rail items={CAST} renderItem={person => <PersonCard person={person} onOpen={openPerson} />}
        title="Cast" summary="Signal Fires · season one" summaryInline={`${CAST.length} people`}
        itemWidth={132} emptyLabel="No cast available." />

      <MediumExtras reading={READING} youtubeWatch={YOUTUBE_WATCH}
        onOpenItem={item => navigate?.('Detail', { item: { title: item.name || item.title } })} />
    </> : null}

    {view === 'studio' ? <>
      <StudioHero studio={DEMO_STUDIO} counts={STUDIO_COUNTS} onOpenWebsite={openExternal} />

      <Rail items={STUDIO_TITLES} renderItem={entry => <CreditCard entry={entry} onOpen={openCredit} />}
        title="Games" summary={`${STUDIO_TITLES.length} titles`} summaryInline="Newest first"
        itemWidth={176} emptyLabel="No titles available." />

      <MediumExtras gameLengths={GAME_LENGTHS} onOpenSource={openExternal} />
    </> : null}

    {view === 'extras' ? <>
      <Section title="Trailers and photos" copy="Signal Fires · season one">
        <MediaGallery items={GALLERY}
          onPlay={item => openExternal(item.key ? `https://www.youtube.com/watch?v=${item.key}` : item.url)}
          onOpenLightbox={(items, index) => setLightbox({ visible: true, index })} />
      </Section>

      <Section title="Medium extras">
        <MediumExtras gameLengths={GAME_LENGTHS} youtubeWatch={YOUTUBE_WATCH} reading={READING}
          onOpenSource={openExternal}
          onOpenItem={item => navigate?.('Detail', { item: { title: item.name || item.title } })} />
      </Section>
    </> : null}

    <Note surface={surface} compact />

    <LightboxDialog visible={lightbox.visible} items={GALLERY} index={lightbox.index}
      onClose={() => setLightbox({ visible: false, index: lightbox.index })}
      onIndexChange={index => setLightbox({ visible: true, index })}
      onPlay={item => openExternal(item.key ? `https://www.youtube.com/watch?v=${item.key}` : item.url)} />
  </Screen>;
}

const styles = StyleSheet.create({
  menu: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  menuItem: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1 },
  menuText: { fontSize: 13, fontWeight: '600' },
});
