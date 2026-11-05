const cover = seed => `https://picsum.photos/seed/floppy-${seed}/600/600`;

const listen = (id, date, time, extra = {}) => ({ id, date, time, ...extra });

const track = (input) => ({
  disc: 1,
  score: null,
  notes: '',
  codec: '',
  listens: [],
  ...input,
});

export const musicDemo = {
  artist: {
    id: 'mira-vale',
    name: 'Mira Vale',
    image: cover('mira-vale'),
    type: 'Group',
    origin: 'Reykjavík, Iceland',
    formed: '2016',
    genres: ['Dream Pop', 'Shoegaze', 'Electronic'],
    status: 'In progress',
    score: 9,
    notes: 'Followed after the Glass Meridian release show.',
    totalPlays: 148,
    musicbrainz: { rating: 8.4, votes: 1240 },
    bio: 'Mira Vale is a Reykjavík dream-pop trio built on close harmonies, bowed guitar and slow-moving synthesizers. Their records pair wide, weather-heavy textures with songs that stay small and personal.',
    collection: { albums: 4, totalAlbums: 4, tracks: 38, totalTracks: 44 },
    relations: {
      members: [
        {
          id: 'elva-run',
          name: 'Elva Rún',
          role: 'Vocals, synthesizers',
          current: true,
          image: cover('elva-run'),
          status: 'In progress',
          score: 8,
        },
        {
          id: 'jonas-kerr',
          name: 'Jónas Kerr',
          role: 'Guitar, production',
          current: true,
          image: cover('jonas-kerr'),
          status: 'Completed',
          score: 9,
        },
        {
          id: 'salka-voss',
          name: 'Salka Voss',
          role: 'Bass, strings',
          current: false,
          image: cover('salka-voss'),
          status: null,
          score: null,
        },
      ],
      alsoIn: [
        {
          id: 'aurora-static',
          name: 'Aurora Static',
          role: 'Member',
          current: true,
          image: cover('aurora-static'),
          status: 'Planning',
          score: 7,
        },
        {
          id: 'low-tide-choir',
          name: 'Low Tide Choir',
          role: 'Guest',
          current: false,
          image: cover('low-tide-choir'),
          status: null,
          score: null,
        },
      ],
    },
    discography: [
      {
        label: 'Albums',
        albums: [
          {
            id: 'glass-meridian',
            title: 'Glass Meridian',
            status: 'Completed',
            releaseType: 'Album',
            year: '2025',
            releaseDate: '2025-03-14',
            image: cover('glass-meridian'),
            score: 9,
            plays: 64,
            runtime: '28m',
            format: 'Vinyl · 180g',
            genres: ['Dream Pop', 'Shoegaze'],
            notes: 'The late-night record. Side B is the reason.',
            tracks: [
              track({ id: 'harbour-lights', number: 1, title: 'Harbour Lights', duration: '4:12', score: 9, codec: 'FLAC · 24-bit', notes: 'The line about the ferry still gets me.', listens: [listen('hl-3', '2026-11-02', '21:14'), listen('hl-2', '2026-10-28', '07:42'), listen('hl-1', '2026-10-21', '22:05')] }),
              track({ id: 'glass-meridian-track', number: 2, title: 'Glass Meridian', duration: '5:06', score: 8, codec: 'FLAC · 24-bit', listens: [listen('gm-2', '2026-10-30', '18:20'), listen('gm-1', '2026-10-21', '22:10')] }),
              track({ id: 'low-cloud', number: 3, title: 'Low Cloud', duration: '3:48', score: null, codec: 'FLAC · 16-bit', listens: [listen('lc-1', '2026-10-26', '06:55')] }),
              track({ id: 'cartography', number: 4, title: 'Cartography', duration: '4:31' }),
              track({ id: 'salt-air', number: 5, title: 'Salt Air', duration: '6:02', score: 7, codec: 'FLAC · 24-bit', listens: [listen('sa-1', '2026-10-24', '23:38')] }),
              track({ id: 'return-signal', number: 6, title: 'Return Signal', duration: '4:58' }),
            ],
          },
          {
            id: 'tidal-rooms',
            title: 'Tidal Rooms',
            status: 'Completed',
            releaseType: 'Album',
            year: '2023',
            releaseDate: '2023-09-08',
            image: cover('tidal-rooms'),
            score: 8,
            plays: 46,
            runtime: '21m',
            format: 'Digital · 24-bit',
            genres: ['Dream Pop'],
            notes: '',
            tracks: [
              track({ id: 'tidal-rooms-title', number: 1, title: 'Tidal Rooms', duration: '4:44', score: 8, codec: 'FLAC · 24-bit', listens: [listen('tr-2', '2026-10-18', '20:02'), listen('tr-1', '2026-10-11', '19:44')] }),
              track({ id: 'window-seat', number: 2, title: 'Window Seat', duration: '3:57', score: 7 }),
              track({ id: 'blue-hour', number: 3, title: 'Blue Hour', duration: '5:21' }),
              track({ id: 'undertow', number: 4, title: 'Undertow', duration: '6:32' }),
            ],
          },
        ],
      },
      {
        label: 'EPs',
        albums: [
          {
            id: 'static-bloom',
            title: 'Static Bloom',
            status: 'In progress',
            releaseType: 'EP',
            year: '2021',
            releaseDate: '2021-05-21',
            image: cover('static-bloom'),
            score: 7,
            plays: 28,
            runtime: '14m',
            format: 'Digital',
            genres: ['Shoegaze'],
            notes: '',
            tracks: [
              track({ id: 'static-bloom-title', number: 1, title: 'Static Bloom', duration: '4:05', score: 7 }),
              track({ id: 'paper-weather', number: 2, title: 'Paper Weather', duration: '4:38' }),
              track({ id: 'small-hours', number: 3, title: 'Small Hours', duration: '5:02' }),
            ],
          },
        ],
      },
      {
        label: 'Live',
        albums: [
          {
            id: 'live-at-husid',
            title: 'Live at Húsið',
            status: 'Planning',
            releaseType: 'Live',
            year: '2024',
            releaseDate: '2024-11-02',
            image: cover('live-at-husid'),
            score: null,
            plays: 10,
            runtime: '18m',
            format: 'Digital',
            genres: ['Dream Pop'],
            notes: '',
            tracks: [
              track({ id: 'harbour-lights-live', number: 1, title: 'Harbour Lights (live)', duration: '4:40', score: 8 }),
              track({ id: 'glass-meridian-live', number: 2, title: 'Glass Meridian (live)', duration: '5:52' }),
            ],
          },
        ],
      },
    ],
  },
  show: {
    id: 'signal-static',
    title: 'Signal & Static',
    author: 'Marguerite Okafor',
    image: cover('signal-static'),
    genres: ['Technology', 'Society & Culture'],
    status: 'In progress',
    score: 8,
    notes: 'Start with the transmission towers episode.',
    description: 'Field recordings, old transmitters and the people who keep them running. Each episode follows one signal from its source to the edge of its range.',
    episodes: [
      { id: 'quiet-frequency', number: 9, title: 'The Quiet Frequency', published: '2026-10-28', minutes: 52, duration: '52 min', score: 9, inProgress: false, notes: 'A perfect closing episode.', plays: [listen('ep9-1', '2026-10-29', '08:12', { minutes: 52 })] },
      { id: 'dead-air', number: 8, title: 'Dead Air', published: '2026-10-21', minutes: 46, duration: '46 min', score: 8, inProgress: false, notes: 'The silence experiment is worth replaying.', plays: [listen('ep8-2', '2026-10-24', '21:08', { minutes: 46 }), listen('ep8-1', '2026-10-22', '07:30', { minutes: 46 })] },
      { id: 'salt-marsh-repeater', number: 7, title: 'Salt Marsh Repeater', published: '2026-10-14', minutes: 41, duration: '41 min', score: 7, inProgress: false, notes: '', plays: [listen('ep7-1', '2026-10-16', '18:42', { minutes: 41 })] },
      { id: 'the-long-wave', number: 6, title: 'The Long Wave', published: '2026-10-07', minutes: 58, duration: '58 min', score: null, inProgress: false, notes: '', plays: [listen('ep6-1', '2026-10-09', '12:20', { minutes: 58 })] },
      { id: 'night-shift', number: 5, title: 'Night Shift', published: '2026-09-30', minutes: 55, duration: '55 min', score: null, inProgress: true, notes: '', plays: [listen('ep5-1', '2026-10-02', '23:10', { minutes: 34, progress: '21 min left' })] },
      { id: 'carrier-wave', number: 4, title: 'Carrier Wave', published: '2026-09-23', minutes: 44, duration: '44 min', score: null, inProgress: false, notes: '', plays: [] },
      { id: 'border-transmission', number: 3, title: 'Border Transmission', published: '2026-09-16', minutes: 49, duration: '49 min', score: null, inProgress: false, notes: '', plays: [] },
      { id: 'the-antenna-field', number: 2, title: 'The Antenna Field', published: '2026-09-09', minutes: 47, duration: '47 min', score: null, inProgress: false, notes: '', plays: [] },
      { id: 'first-signal', number: 1, title: 'First Signal', published: '2026-09-02', minutes: 39, duration: '39 min', score: null, inProgress: false, notes: '', plays: [] },
    ],
  },
};

export function createMusicLibrary() {
  return JSON.parse(JSON.stringify(musicDemo));
}

export function flattenAlbums(artist) {
  return artist.discography.flatMap(group => group.albums || []);
}

export function findTrack(library, trackId) {
  for (const group of library.artist.discography) {
    for (const album of group.albums || []) {
      const found = album.tracks.find(entry => entry.id === trackId);
      if (found) return { album, track: found };
    }
  }
  return null;
}

export function findAlbum(library, albumId) {
  return flattenAlbums(library.artist).find(album => album.id === albumId) || null;
}

export function episodeState(episode) {
  if (!episode.plays.length) return 'unplayed';
  if (episode.inProgress) return 'in_progress';
  return 'played';
}
