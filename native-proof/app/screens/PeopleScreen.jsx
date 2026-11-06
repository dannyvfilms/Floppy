import React, { useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { PeopleView } from '../../../frontend/pages/PeopleView';
import { LightboxDialog } from '../../../frontend/ui/People';
import { Screen, Section } from '../components/Screen';
import { createPeopleTransport } from '../data/peopleTransport';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'PEOPLE',
  status: 'in_progress',
  title: 'People, studios and credits',
  where: 'Person and studio pages, cast/crew/filmography/credit rows, trailers, lightbox and medium extras',
  note: 'Person and studio heroes, watched/filmography credit rails and studio title rails load through the authenticated profile transport, with realistic person, studio and detail-extra demos kept only when no identity is supplied. Cast, crew, gallery, lightbox and medium-extra rails render the shared native presentation, and the same rails accept cast/crew/gallery/extras payloads from navigation params or, for crew, a profile payload. Exact blockers: the person and studio JSON contract still carries no cast, crew, gallery or extras payload, so live profiles show only hero and credit rails; permissions and iOS/Android runtime verification remain outstanding.',
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
  { id: 'eli', name: 'Eli Mercer', subtitle: 'Chief Arlo Dane', episodeCount: 12,
    imageUrl: 'https://picsum.photos/seed/floppy-person-eli/300/450' },
  { id: 'mira', name: 'Mira Adeyemi', subtitle: 'Dr. Sena Okafor', episodeCount: 10,
    imageUrl: 'https://picsum.photos/seed/floppy-person-mira/300/450' },
  { id: 'tomas', name: 'Tomás Ibarra', subtitle: 'Rafael Quill', episodeCount: 8,
    imageUrl: 'https://picsum.photos/seed/floppy-person-tomas/300/450' },
  { id: 'june', name: 'June Park', subtitle: 'Lena Hsu', episodeCount: 6,
    imageUrl: 'https://picsum.photos/seed/floppy-person-june/300/450' },
];

const CREW = [
  { id: 'harriet', name: 'Harriet Okonkwo', subtitle: 'Director', lines: ['Directing'],
    imageUrl: 'https://picsum.photos/seed/floppy-crew-harriet/300/450' },
  { id: 'samuel', name: 'Samuel Reyes', subtitle: 'Writer', lines: ['Writing'],
    imageUrl: 'https://picsum.photos/seed/floppy-crew-samuel/300/450' },
  { id: 'ines', name: 'Inés Duarte', subtitle: 'Cinematographer', lines: ['Camera'],
    imageUrl: 'https://picsum.photos/seed/floppy-crew-ines/300/450' },
  { id: 'arlo', name: 'Arlo Voss', subtitle: 'Composer', lines: ['Sound'],
    imageUrl: 'https://picsum.photos/seed/floppy-crew-arlo/300/450' },
  { id: 'priya', name: 'Priya Nandakumar', subtitle: 'Production Designer', lines: ['Art'],
    imageUrl: 'https://picsum.photos/seed/floppy-crew-priya/300/450' },
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
  { id: 'harbour-lights', title: 'Harbour Lights', mediaTypeLabel: 'Game', mediaType: 'game', year: 2025,
    role: 'Developer, Publisher', imageUrl: 'https://picsum.photos/seed/floppy-harbour-lights/400/600',
    watchedRuntimeLabel: '12h tracked', watched: true },
  { id: 'salt-and-iron', title: 'Salt & Iron', mediaTypeLabel: 'Game', mediaType: 'game', year: 2024,
    role: 'Developer', imageUrl: 'https://picsum.photos/seed/floppy-salt-iron/400/600', voteAverage: 8.4 },
  { id: 'north-sea-radio', title: 'North Sea Radio', mediaTypeLabel: 'Game', mediaType: 'game', year: 2023,
    role: 'Developer, Publisher', imageUrl: 'https://picsum.photos/seed/floppy-radio/400/600', voteAverage: 7.9 },
  { id: 'the-long-wake', title: 'The Long Wake', mediaTypeLabel: 'Game', mediaType: 'game', year: 2022,
    role: 'Developer', imageUrl: 'https://picsum.photos/seed/floppy-long-wake/400/600', voteAverage: 8.1 },
  { id: 'tidal-lock', title: 'Tidal Lock', mediaTypeLabel: 'Game', mediaType: 'game', year: 2020,
    role: 'Publisher', imageUrl: 'https://picsum.photos/seed/floppy-tidal-lock/400/600', voteAverage: 7.4 },
  { id: 'lantern-keepers', title: 'Lantern Keepers', mediaTypeLabel: 'Game', mediaType: 'game', year: 2018,
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

function identityFrom(params) {
  if (!params) return null;
  if (params.kind === 'studio' || params.studioId) {
    if (!params.source || !params.studioId) return null;
    return {
      kind: 'studio',
      source: params.source,
      studioId: String(params.studioId),
      slug: params.slug || 'profile',
    };
  }
  if (params.kind === 'person' || params.personId) {
    if (!params.source || !params.personId) return null;
    return {
      kind: 'person',
      source: params.source,
      personId: String(params.personId),
      slug: params.slug || 'profile',
    };
  }
  return null;
}

export default function PeopleScreen({ navigate, onBack, params, transport: injectedTransport }) {
  const [transport] = useState(() => injectedTransport || createPeopleTransport());
  const identity = identityFrom(params);
  const [mode, setMode] = useState(() => (params?.profile ? 'ready' : identity ? 'loading' : 'demo'));
  const [profile, setProfile] = useState(params?.profile || null);
  const [error, setError] = useState('');
  const [view, setView] = useState(params?.kind === 'extras' ? 'extras' : identity?.kind === 'studio' ? 'studio' : 'person');
  const [lightbox, setLightbox] = useState({ visible: false, index: 0 });

  useEffect(() => {
    let active = true;
    if (!identity) {
      setProfile(params?.profile || null);
      setMode(params?.profile ? 'ready' : 'demo');
      return () => { active = false; };
    }
    if (params?.profile) {
      setProfile(params.profile);
      setMode('ready');
      return () => { active = false; };
    }
    setMode('loading');
    setError('');
    const request = identity.kind === 'studio'
      ? transport.loadStudio(identity)
      : transport.loadPerson(identity);
    Promise.resolve(request).then(data => {
      if (!active) return;
      if (data?.local) {
        setProfile(null);
        setMode('demo');
        setError(data.reason || 'Sign in to load this profile from your server.');
        return;
      }
      setProfile(data);
      setMode('ready');
    }).catch(requestError => {
      if (!active) return;
      setProfile(null);
      setMode('error');
      setError(requestError?.message || 'The server rejected the profile request.');
    });
    return () => { active = false; };
  }, [transport, identity?.kind, identity?.source, identity?.personId, identity?.studioId, identity?.slug, params?.profile]);

  function openCredit(entry) {
    navigate?.('Detail', {
      item: {
        title: entry.title,
        mediaType: entry.mediaType,
        source: entry.source,
        mediaId: entry.mediaId,
      },
    });
  }

  function openPerson(person) {
    if (person.personId && person.source) {
      navigate?.('People', {
        kind: 'person',
        source: person.source,
        personId: person.personId,
        slug: person.slug,
      });
      return;
    }
    navigate?.('Detail', { item: { title: person.name } });
  }

  function openExtra(item) {
    navigate?.('Detail', {
      item: {
        title: item.name || item.title,
        mediaType: item.mediaType,
        source: item.source,
        mediaId: item.mediaId,
      },
    });
  }

  function playGalleryItem(item) {
    openExternal(item.key ? `https://www.youtube.com/watch?v=${item.key}` : item.url);
  }

  function extrasView(extras) {
    const gallery = params?.gallery || profile?.gallery || [];
    const labels = profile?.labels;
    const gameLengths = extras?.gameLengths;
    const youtubeWatch = extras?.youtubeWatch;
    const reading = extras?.reading;
    if (!gallery.length && !gameLengths && !youtubeWatch && !reading) return null;
    return <PeopleView
      part="extras"
      gallery={gallery}
      galleryTitle={params?.galleryTitle || profile?.person?.name || profile?.studio?.name || ''}
      gameLengths={gameLengths}
      youtubeWatch={youtubeWatch}
      reading={reading}
      labels={labels}
      palette={palette}
      onOpenSource={openExternal}
      onOpenExtra={openExtra}
      onPlayGallery={playGalleryItem}
      onOpenLightbox={(items, index) => setLightbox({ visible: true, index })} />;
  }

  function livePerson(personProfile) {
    const person = personProfile.person;
    const labels = personProfile.labels || {};
    const extras = params?.extras || personProfile.extras || {};
    const gallery = params?.gallery || personProfile.gallery || [];
    return <PeopleView
      part="full"
      kind="person"
      person={person}
      counts={personProfile.counts}
      labels={labels}
      palette={palette}
      watched={personProfile.watched || []}
      filmography={personProfile.filmography || []}
      cast={params?.cast || personProfile.cast || []}
      crew={params?.crew || personProfile.crew || []}
      gallery={gallery}
      galleryTitle={params?.galleryTitle || person?.name || ''}
      gameLengths={extras.gameLengths}
      youtubeWatch={extras.youtubeWatch}
      reading={extras.reading}
      isAuthor={personProfile.isAuthor}
      showBiography={personProfile.showBiography}
      canViewHistory={personProfile.canViewHistory}
      actionPalette={{ radius: radius.md || 8 }}
      onOpenSource={openExternal}
      onViewHistory={personProfile.historyUrl
        ? () => navigate?.('History', { filters: personProfile.historyUrl })
        : undefined}
      onOpenCredit={openCredit}
      onOpenPerson={openPerson}
      onOpenExtra={openExtra}
      onPlayGallery={playGalleryItem}
      onOpenLightbox={(items, index) => setLightbox({ visible: true, index })} />;
  }

  function liveStudio(studioProfile) {
    const labels = studioProfile.labels || {};
    const extras = params?.extras || studioProfile.extras || {};
    return <PeopleView
      part="full"
      kind="studio"
      studio={studioProfile.studio}
      counts={studioProfile.counts}
      labels={labels}
      palette={palette}
      filmography={studioProfile.titles || []}
      creditsTitle={studioProfile.studio.mediaLabel || labels.titles || 'Titles'}
      gallery={params?.gallery || studioProfile.gallery || []}
      galleryTitle={params?.galleryTitle || studioProfile.studio?.name || ''}
      gameLengths={extras.gameLengths}
      youtubeWatch={extras.youtubeWatch}
      reading={extras.reading}
      sourcePlacement="facts"
      showBiography={studioProfile.showBiography}
      onOpenWebsite={openExternal}
      onOpenSource={openExternal}
      onOpenCredit={openCredit}
      onOpenExtra={openExtra}
      onPlayGallery={playGalleryItem}
      onOpenLightbox={(items, index) => setLightbox({ visible: true, index })} />;
  }

  const demoGallery = params?.gallery?.length ? params.gallery : GALLERY;
  const demoExtras = params?.extras || {};
  const demoGameLengths = demoExtras.gameLengths || GAME_LENGTHS;
  const demoYoutubeWatch = demoExtras.youtubeWatch || YOUTUBE_WATCH;
  const demoReading = demoExtras.reading || READING;

  function demoView() {
    return <>
      <Menu value={view} onChange={setView} />
      {view === 'person' ? <PeopleView
        part="full"
        kind="person"
        person={DEMO_PERSON}
        counts={PERSON_COUNTS}
        palette={palette}
        watched={WATCHED_CREDITS}
        filmography={FILMOGRAPHY}
        cast={CAST}
        crew={CREW}
        youtubeWatch={demoYoutubeWatch}
        reading={demoReading}
        onViewHistory={() => navigate?.('History')}
        onOpenSource={openExternal}
        onOpenCredit={openCredit}
        onOpenPerson={openPerson}
        onOpenExtra={openExtra} /> : null}
      {view === 'studio' ? <PeopleView
        part="full"
        kind="studio"
        studio={DEMO_STUDIO}
        counts={STUDIO_COUNTS}
        palette={palette}
        filmography={STUDIO_TITLES}
        creditsTitle="Games"
        gameLengths={demoGameLengths}
        onOpenWebsite={openExternal}
        onOpenSource={openExternal}
        onOpenCredit={openCredit}
        onOpenExtra={openExtra} /> : null}
      {view === 'extras' ? <PeopleView
        part="extras"
        gallery={demoGallery}
        galleryTitle={params?.galleryTitle || 'Signal Fires · season one'}
        gameLengths={demoGameLengths}
        youtubeWatch={demoYoutubeWatch}
        reading={demoReading}
        palette={palette}
        onOpenSource={openExternal}
        onOpenExtra={openExtra}
        onPlayGallery={playGalleryItem}
        onOpenLightbox={(items, index) => setLightbox({ visible: true, index })} /> : null}
    </>;
  }

  const live = mode === 'ready' && profile;
  const liveKind = live?.kind;
  const liveLightboxItems = live ? (params?.gallery || profile?.gallery || []) : demoGallery;

  return <Screen title="People, studios" subtitle="People, studios and credits" onBack={onBack}>
    {mode === 'loading' ? <Section title="Loading profile">
      <Text style={styles.statusText}>Loading the person or studio profile from your server.</Text>
    </Section> : null}
    {mode === 'error' ? <Section title="Profile unavailable">
      <Text accessibilityLiveRegion="polite" style={styles.statusText}>{error}</Text>
    </Section> : null}
    {identity && !live && mode === 'demo' && error ? <Section title="Local preview">
      <Text accessibilityLiveRegion="polite" style={styles.statusText}>{error}</Text>
    </Section> : null}
    {liveKind === 'person' ? livePerson(profile) : null}
    {liveKind === 'studio' ? liveStudio(profile) : null}
    {!identity ? demoView() : null}
    <LightboxDialog visible={lightbox.visible} items={liveLightboxItems} index={lightbox.index}
      palette={palette}
      onClose={() => setLightbox({ visible: false, index: lightbox.index })}
      onIndexChange={index => setLightbox({ visible: true, index })}
      onPlay={playGalleryItem} />
  </Screen>;
}

const styles = StyleSheet.create({
  menu: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  menuItem: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1 },
  menuText: { fontSize: 13, fontWeight: '600' },
  statusText: { color: palette.textSecondary, fontSize: 14, lineHeight: 20 },
});
