import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { HomeView } from '../../../frontend/pages/HomeView';
import { Icon } from '../../../frontend/ui/Icon';
import { shelfCardWidth } from '../../../frontend/ui/HomeShelves';
import { Rail } from '../../../frontend/ui/Rail.jsx';
import {
  createHomeTransport,
  homeScreenFromPayload,
  mergeHomeRowPage,
} from '../data/homeTransport';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { palette, radius, spacing } from '../theme';
import { Screen } from '../components/Screen';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import PlaybackSlot from '../surfaces/PlaybackSlot';

export const surface = {
  id: 'HOME',
  status: 'ported',
  title: 'Home shelves, deferred groups and cover refresh',
  where: 'Home screen shelves, media-type sections, deferred rows and coalesced artwork polling',
  note: 'The native Home screen composes the shared search field, Now Playing card, HomeShelves rails and cards, and the shared media card grid. It renders realistic demo shelves when signed out and loads bounded server groups, deferred rows, sort direction, load-more pages and cover refreshes through homeTransport when signed in, with loading, empty, error/retry and deferred-skeleton states. The user reports extensive use in Expo Go and considers Home done for the current milestone; handle follow-up issues as individual bug reports. Known follow-up gaps: shelf card action and link intents route to Detail instead of opening the shared Track/Lists action host or their target link, and Home Screen settings has no native route, so the screen inlines the shared editor. Device, OS, version and specific interaction coverage were not recorded; see the UI verification registry.',
};

const PAGE_LIMIT = 14;

const emptyModel = () => ({
  groups: [],
  deferredGroups: [],
  showMediaTypeHeaders: false,
  readOnly: true,
  labels: {},
});

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Sample data has no artwork. Returning null makes the shared card render the
// same flat placeholder the web uses for an item without a poster, instead of
// loading unrelated stock photos from an external host.
function artwork() {
  return null;
}

function line(meta) {
  const parts = (Array.isArray(meta) ? meta : [meta])
    .filter(part => part != null && part !== '')
    .map((text, index) => ({ text: String(text), muted: index > 0 }));
  return { join: 'dot', parts };
}

function card(input) {
  const href = input.href || `/demo/${input.seed}`;
  const cornerChips = [];
  if (input.next) {
    cornerChips.push({ kind: 'next-episode', text: input.next, href: `${href}/next` });
  }
  if (input.runtime) cornerChips.push({ kind: 'runtime', text: input.runtime });
  if (input.plays) cornerChips.push({ kind: 'runtime', text: input.plays });
  return {
    mediaType: input.mediaType,
    identity: {
      mediaType: input.mediaType,
      source: 'demo',
      mediaId: String(input.seed),
      title: input.title,
    },
    shape: input.shape || 'poster',
    video: false,
    href,
    image: Object.prototype.hasOwnProperty.call(input, 'image')
      ? input.image
      : artwork(input.seed, input.shape),
    title: input.title,
    altTitle: input.altTitle || null,
    statusChip: input.status
      ? { kind: 'status', status: input.status, label: `Status: ${input.status}` }
      : null,
    cornerChips,
    titleLinks: [],
    progressBar: input.progress == null
      ? null
      : { percent: input.progress, paused: Boolean(input.paused) },
    lines: [line(input.meta || '')],
    actions: null,
    cardKey: `demo-${input.mediaType}-${input.seed}`,
    rating: input.rating || null,
    ratingEditable: false,
    csrfToken: '',
  };
}

function row(input) {
  const loaded = input.loaded ?? input.pool.length;
  return {
    rowId: input.rowId,
    title: input.title,
    titleMain: input.title,
    titleDetail: input.titleDetail || null,
    summary: input.summary || '',
    summaryInline: input.summaryInline || null,
    direction: input.direction || 'desc',
    total: input.pool.length,
    seed: input.seed ?? 0,
    loadedCount: loaded,
    showPlayedChip: false,
    showMediaTypeChip: false,
    mixedMedia: false,
    videoLandscape: false,
    pollForCovers: Boolean(input.pollForCovers),
    items: input.pool.slice(0, loaded).map((model, index) => ({
      id: `${input.rowId}-${index}`,
      card: model,
    })),
  };
}

const tvNextPool = [
  card({
    mediaType: 'tv', title: 'The Bear', seed: 'the-bear', meta: ['S3 E4', 'Hulu'],
    status: 'In progress', next: 'S3 E4', progress: 64,
    rating: { label: '8.6', value: 8.6, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'tv', title: 'Severance', seed: 'severance', meta: ['S2 E1', 'Apple TV+'],
    status: 'In progress', next: 'S2 E1', progress: 22,
    rating: { label: '8.9', value: 8.9, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'tv', title: 'Andor', seed: 'andor', meta: ['S2 E2', 'Disney+'],
    status: 'In progress', next: 'S2 E2', progress: 48,
  }),
  card({
    mediaType: 'tv', title: 'The Last of Us', seed: 'last-of-us', meta: ['S1 E7', 'Max'],
    status: 'In progress', next: 'S1 E7', progress: 80,
  }),
  card({
    mediaType: 'tv', title: 'Shrinking', seed: 'shrinking', meta: ['S2 E3', 'Apple TV+'],
    status: 'In progress', next: 'S2 E3', progress: 10,
  }),
  card({
    mediaType: 'tv', title: 'Slow Horses', seed: 'slow-horses', meta: ['S3 E2', 'Apple TV+'],
    status: 'In progress', next: 'S3 E2', progress: 35,
  }),
];

function airedPool(hydrated) {
  const image = hydrated ? artwork('silo') : null;
  return [
    card({
      mediaType: 'tv', title: 'Silo', seed: 'silo', meta: ['S2 E4', 'Apple TV+'],
      status: 'In progress', next: 'S2 E4', progress: 38, image,
    }),
    card({
      mediaType: 'tv', title: 'The Diplomat', seed: 'the-diplomat', meta: ['S3 E1', 'Netflix'],
      status: 'In progress', next: 'S3 E1', progress: 12,
      image: hydrated ? artwork('the-diplomat') : null,
    }),
    card({
      mediaType: 'tv', title: 'Foundation', seed: 'foundation', meta: ['S3 E2', 'Apple TV+'],
      status: 'In progress', next: 'S3 E2', progress: 55,
      image: hydrated ? artwork('foundation') : null,
    }),
  ];
}

const moviePlannedPool = [
  card({
    mediaType: 'movie', title: 'Dune: Part Two', seed: 'dune-part-two',
    meta: ['2024', 'Film'], status: 'Planning', runtime: '2h 46m',
    rating: { label: '8.6', value: 8.6, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'movie', title: 'Past Lives', seed: 'past-lives',
    meta: ['2023', 'Film'], status: 'Planning', runtime: '1h 46m',
    rating: { label: '7.9', value: 7.9, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'movie', title: 'Poor Things', seed: 'poor-things',
    meta: ['2023', 'Film'], status: 'Planning', runtime: '2h 21m',
  }),
  card({
    mediaType: 'movie', title: 'The Zone of Interest', seed: 'zone-of-interest',
    meta: ['2023', 'Film'], status: 'Planning', runtime: '1h 45m',
  }),
];

const bookPool = [
  card({
    mediaType: 'book', title: 'Project Hail Mary', seed: 'project-hail-mary',
    meta: ['Andy Weir', '205 of 496 pages'], status: 'In progress', progress: 41,
  }),
  card({
    mediaType: 'book', title: 'Piranesi', seed: 'piranesi',
    meta: ['Susanna Clarke', '128 pages left'], status: 'In progress', progress: 72,
  }),
  card({
    mediaType: 'book', title: 'The Lantern Keeper', seed: 'the-lantern-keeper',
    meta: ['Fantasy', '18 pages today'], status: 'In progress', progress: 18,
  }),
];

const musicPool = [
  card({
    mediaType: 'music', title: 'Night Drive', seed: 'night-drive', shape: 'square',
    meta: ['Album', 'Synthwave'], plays: '6 plays',
  }),
  card({
    mediaType: 'music', title: 'Random Access Memories', seed: 'random-access-memories',
    shape: 'square', meta: ['Album', 'Electronic'], plays: '4 plays',
  }),
  card({
    mediaType: 'music', title: 'Blonde', seed: 'blonde', shape: 'square',
    meta: ['Album', 'R&B'], plays: '2 plays',
  }),
];

const animePool = [
  card({
    mediaType: 'anime', title: "Frieren: Beyond Journey's End", seed: 'frieren',
    meta: ['S2 E4', 'Crunchyroll'], status: 'In progress', next: 'S2 E4', progress: 36,
    rating: { label: '9.1', value: 9.1, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'anime', title: 'Solo Leveling', seed: 'solo-leveling',
    meta: ['S2 E5', 'Crunchyroll'], status: 'In progress', next: 'S2 E5', progress: 62,
  }),
  card({
    mediaType: 'anime', title: 'The Apothecary Diaries', seed: 'apothecary-diaries',
    meta: ['S2 E3', 'Crunchyroll'], status: 'In progress', next: 'S2 E3', progress: 20,
  }),
  card({
    mediaType: 'anime', title: 'Dandadan', seed: 'dandadan', meta: ['S2 E6', 'Netflix'],
    status: 'In progress', next: 'S2 E6', progress: 75,
  }),
];

const gamesPool = [
  card({
    mediaType: 'game', title: 'Hades II', seed: 'hades-two', shape: 'square',
    meta: ['14h played', 'Early access'], status: 'In progress', progress: 42,
    rating: { label: '9.1', value: 9.1, scaleMax: 10, rateLabel: 'Rate' },
  }),
  card({
    mediaType: 'game', title: 'Balatro', seed: 'balatro', shape: 'square',
    meta: ['9h played', 'Deck builder'], status: 'In progress', progress: 28,
  }),
  card({
    mediaType: 'game', title: 'Animal Well', seed: 'animal-well', shape: 'square',
    meta: ['3h played', 'Puzzle'], status: 'In progress', progress: 12,
  }),
];

const demoRowDefs = {
  'tv-next-up': {
    title: 'Next up', titleDetail: 'This week', summaryInline: 'Next 6',
    summary: 'Episodes waiting after what you last watched.',
    pool: tvNextPool, loaded: 4,
  },
  'tv-recently-aired': {
    title: 'Recently aired', titleDetail: 'New episodes', summaryInline: 'Updated today',
    summary: 'Fresh episodes from shows you follow.', pool: airedPool(false),
    pollForCovers: true,
  },
  'movie-planned': {
    title: 'Planned', titleDetail: 'Watchlist', summaryInline: '4 saved',
    summary: 'Films saved for later.', pool: moviePlannedPool, loaded: 3,
  },
  'book-reading': {
    title: 'Reading now', summaryInline: '2 reading',
    summary: 'Continue where you left off.', pool: bookPool, loaded: 2,
  },
  'music-recent': {
    title: 'Recently played', summaryInline: 'Last 7 days',
    summary: 'Albums from the last seven days.', pool: musicPool,
  },
  'podcast-new': {
    title: 'New episodes', summaryInline: 'Nothing new',
    summary: 'Unplayed episodes from shows you follow.', pool: [],
  },
  'anime-season': {
    title: 'Airing this season', titleDetail: 'Winter 2026', summaryInline: 'Updated weekly',
    summary: 'Fresh episodes from shows you follow.', pool: animePool, deferMs: 650,
  },
  'games-continue': {
    title: 'Continue playing', summaryInline: '3 in progress',
    summary: 'Pick up where you left off.', pool: gamesPool, deferMs: 500,
  },
};

const demoRows = Object.fromEntries(
  Object.entries(demoRowDefs).map(([rowId, definition]) => [rowId, row({ ...definition, rowId })]),
);
const demoRowPools = Object.fromEntries(
  Object.entries(demoRowDefs).map(([rowId, definition]) => [rowId, definition.pool]),
);

function hydratedAiredRow() {
  return row({
    ...demoRowDefs['tv-recently-aired'],
    rowId: 'tv-recently-aired',
    pool: airedPool(true),
    pollForCovers: false,
  });
}

function demoModel() {
  return {
    groups: [
      {
        mediaType: 'tv',
        label: 'TV Shows',
        rows: [demoRows['tv-next-up'], demoRows['tv-recently-aired']],
      },
      { mediaType: 'movie', label: 'Movies', rows: [demoRows['movie-planned']] },
      { mediaType: 'book', label: 'Books', rows: [demoRows['book-reading']] },
      { mediaType: 'music', label: 'Music', rows: [demoRows['music-recent']] },
      { mediaType: 'podcast', label: 'Podcasts', rows: [demoRows['podcast-new']] },
    ],
    deferredGroups: [
      { mediaType: 'anime', label: 'Anime', rowIds: ['anime-season'] },
      { mediaType: 'games', label: 'Games', rowIds: ['games-continue'] },
    ],
    showMediaTypeHeaders: true,
    readOnly: false,
    labels: {},
  };
}

export default function HomeScreen({ navigate }) {
  const { width } = useWindowDimensions();
  // The same breakpoint helper the web mount uses, so a card is never a
  // different size on one surface.
  const itemWidth = shelfCardWidth(width);
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => createHomeTransport(session ? { auth: session } : {}),
    [session],
  );
  const serverMode = transport.mode === 'server';
  const [model, setModel] = useState(() => (serverMode ? emptyModel() : demoModel()));
  const [loading, setLoading] = useState(serverMode);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!serverMode) {
      setModel(demoModel());
      setLoading(false);
      setError('');
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    transport.load({ limit: PAGE_LIMIT }).then(payload => {
      if (cancelled) return;
      setModel(homeScreenFromPayload(payload));
      setLoading(false);
    }).catch(cause => {
      if (cancelled) return;
      setError(cause?.message || 'Home could not be loaded from the server.');
      setModel(emptyModel());
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [attempt, serverMode, transport]);

  const loadRow = useCallback(async rowId => {
    if (serverMode) {
      return transport.loadRow({ rowId, limit: PAGE_LIMIT });
    }
    const definition = demoRowDefs[rowId];
    if (!definition) return null;
    await wait(definition.deferMs || 450);
    return demoRows[rowId] || null;
  }, [serverMode, transport]);

  const loadMore = useCallback(async currentRow => {
    if (serverMode) {
      try {
        const page = await transport.loadRow({
          rowId: currentRow.rowId,
          offset: currentRow.loadedCount || 0,
          seed: currentRow.seed,
          limit: PAGE_LIMIT,
        });
        return page ? mergeHomeRowPage(currentRow, page) : null;
      } catch {
        return null;
      }
    }
    const pool = demoRowPools[currentRow.rowId];
    if (!pool) return null;
    const offset = currentRow.loadedCount ?? (currentRow.items || []).length;
    if (offset >= pool.length) return null;
    await wait(400);
    const next = pool.slice(offset, offset + PAGE_LIMIT);
    return {
      ...currentRow,
      items: [
        ...(currentRow.items || []),
        ...next.map((entry, index) => ({
          id: `${currentRow.rowId}-${offset + index}`,
          card: entry,
        })),
      ],
      loadedCount: offset + next.length,
      total: pool.length,
    };
  }, [serverMode, transport]);

  const sortRow = useCallback(async currentRow => {
    if (serverMode) {
      try {
        return await transport.sortRow({ rowId: currentRow.rowId });
      } catch {
        return null;
      }
    }
    await wait(250);
    return {
      ...currentRow,
      items: [...(currentRow.items || [])].reverse(),
      direction: currentRow.direction === 'asc' ? 'desc' : 'asc',
    };
  }, [serverMode, transport]);

  const refreshCovers = useCallback(async (ids = [], pending = 0) => {
    if (serverMode) {
      return transport.refreshCovers({ ids, pending });
    }
    await wait(600);
    if (!ids.includes('tv-recently-aired')) return { rows: [] };
    return { rows: [hydratedAiredRow()], pollRowIds: [] };
  }, [serverMode, transport]);

  return <Screen chrome={false}>
    <HomeView
      notice={serverMode ? null : <View style={[styles.demoNotice, { borderColor: palette.warning || '#f59e0b', backgroundColor: (palette.warning || '#f59e0b') + '14' }]}>
        <Text style={[styles.demoTitle, { color: palette.warning || '#f59e0b' }]}>Demo data</Text>
        <Text style={[styles.demoBody, { color: palette.textSecondary }]}>
          You are signed out, so Home shows sample shelves. Connect your Floppy server to see your own library.
        </Text>
        <Button label="Connect server" tone="surface" palette={palette}
          onPress={() => navigate?.('Auth')} />
      </View>}
      playback={<PlaybackSlot onOpenDetail={card => navigate?.('Detail', { item: {
        identity: {
          mediaType: card.mediaType,
          source: card.source,
          mediaId: card.mediaId,
        },
        title: card.episodeTitle || card.title,
        image: card.image,
        href: card.href,
      } })} />}
      groups={model.groups}
      deferredGroups={model.deferredGroups}
      showMediaTypeHeaders={model.showMediaTypeHeaders}
      labels={model.labels}
      palette={palette}
      readOnly={model.readOnly}
      itemWidth={itemWidth}
      railComponent={Rail}
      renderActionIcon={action => action.icon ? <Icon spec={action.icon} color="#ffffff" size={18} /> : null}
      loading={loading}
      error={error}
      onRetry={() => setAttempt(current => current + 1)}
      onOpenCard={item => navigate?.('Detail', { item: item?.card })}
      onOpenLink={(_href, item) => navigate?.('Detail', { item: item?.card })}
      onAction={(_action, item) => navigate?.('Detail', { item: item?.card })}
      onLoadRow={loadRow}
      onLoadMore={loadMore}
      onSortRow={sortRow}
      onRefreshCovers={refreshCovers}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  demoNotice: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.xs,
    alignItems: 'flex-start',
  },
  demoTitle: { fontSize: 13, fontWeight: '600' },
  demoBody: { fontSize: 13, lineHeight: 18 },
  notice: {
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.4)',
    borderRadius: radius.sm,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    alignItems: 'flex-start',
  },
  noticeText: { color: '#f87171', fontSize: 13, lineHeight: 18 },
  loading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
  },
  loadingText: { color: palette.textMuted, fontSize: 13 },
});
