import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { HomeShelves } from '../../../frontend/ui/HomeShelves';
import {
  createHomeTransport,
  homeScreenFromPayload,
  mergeHomeRowPage,
} from '../data/homeTransport';
import { palette, radius, spacing } from '../theme';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import PlaybackSlot from '../surfaces/PlaybackSlot';
import RailsSlot from '../surfaces/RailsSlot';
import SearchSlot from '../surfaces/SearchSlot';

export const surface = {
  id: 'HOME',
  status: 'in_progress',
  title: 'Home shelves, deferred groups and cover refresh',
  where: 'Home screen shelves, media-type sections, deferred rows and coalesced artwork polling',
  note: 'The shared Home composition renders configured groups, up-next shelves, deferred rows and one coalesced cover poller on the native screen. The transport loads bounded server rows when signed in and keeps realistic demo shelves otherwise. Native iOS and Android runtime interaction remains unverified.',
};

function image(seed) {
  return { src: `https://picsum.photos/seed/floppy-home-${seed}/400/600`, fallback: '', source: 'primary' };
}

function card(input) {
  return {
    mediaType: input.mediaType,
    shape: input.shape || 'poster',
    video: false,
    href: input.href || '/demo/media',
    image: image(input.seed),
    title: input.title,
    altTitle: null,
    statusChip: input.status
      ? { kind: 'status', status: input.status, label: `Status: ${input.status}` }
      : null,
    cornerChips: input.next ? [{ kind: 'next-episode', text: input.next, href: '/demo/next' }] : [],
    titleLinks: [],
    progressBar: input.progress == null ? null : { percent: input.progress, paused: false },
    lines: [{ join: 'plain', parts: [{ text: input.meta || '' }] }],
    actions: null,
    cardKey: `demo-${input.seed}`,
    rating: null,
    ratingEditable: false,
    csrfToken: '',
  };
}

const demoModel = {
  groups: [
    {
      mediaType: 'tv',
      label: 'TV Shows',
      rows: [{
        rowId: 'demo-tv', title: 'Next up', titleMain: 'Next up', titleDetail: null,
        summary: 'Episodes waiting after what you last watched.',
        summaryInline: 'This week', direction: 'desc', total: 4, seed: 0, loadedCount: 4,
        showPlayedChip: false, showMediaTypeChip: false, mixedMedia: false,
        videoLandscape: false, pollForCovers: false,
        items: [
          {
            id: 'bear',
            card: card({
              mediaType: 'tv', title: 'The Bear', meta: 'S3 E4 · Hulu', seed: 'bear',
              status: 'In progress', next: 'S3 E4', progress: 64, href: '/demo/the-bear',
            }),
          },
          {
            id: 'severance',
            card: card({
              mediaType: 'tv', title: 'Severance', meta: 'S2 E1 · Apple TV+', seed: 'severance',
              status: 'In progress', next: 'S2 E1', progress: 22, href: '/demo/severance',
            }),
          },
          {
            id: 'andor',
            card: card({
              mediaType: 'tv', title: 'Andor', meta: 'S2 E2 · Disney+', seed: 'andor',
              status: 'In progress', next: 'S2 E2', progress: 48, href: '/demo/andor',
            }),
          },
          {
            id: 'last-of-us',
            card: card({
              mediaType: 'tv', title: 'The Last of Us', meta: 'S1 E7 · Max', seed: 'last-of-us',
              status: 'In progress', next: 'S1 E7', progress: 80, href: '/demo/the-last-of-us',
            }),
          },
        ],
      }],
    },
    {
      mediaType: 'movie',
      label: 'Movies',
      rows: [{
        rowId: 'demo-movie', title: 'Planned', titleMain: 'Planned', titleDetail: null,
        summary: 'Films saved for later.', summaryInline: null, direction: 'desc',
        total: 3, seed: 0, loadedCount: 3, showPlayedChip: false,
        showMediaTypeChip: false, mixedMedia: false, videoLandscape: false,
        pollForCovers: false,
        items: [
          {
            id: 'dune',
            card: card({
              mediaType: 'movie', title: 'Dune: Part Two', meta: '2024 · Film',
              seed: 'dune', status: 'Planning', href: '/demo/dune-part-two',
            }),
          },
          {
            id: 'past-lives',
            card: card({
              mediaType: 'movie', title: 'Past Lives', meta: '2023 · Film',
              seed: 'past-lives', status: 'Planning', href: '/demo/past-lives',
            }),
          },
          {
            id: 'poor-things',
            card: card({
              mediaType: 'movie', title: 'Poor Things', meta: '2023 · Film',
              seed: 'poor-things', status: 'Planning', href: '/demo/poor-things',
            }),
          },
        ],
      }],
    },
  ],
  deferredGroups: [],
  showMediaTypeHeaders: false,
  readOnly: false,
  labels: {},
};

export default function HomeScreen({ navigate }) {
  const [transport] = useState(() => createHomeTransport());
  const [model, setModel] = useState(demoModel);
  const [transportError, setTransportError] = useState('');

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let cancelled = false;
    transport.load({ limit: 14 }).then(payload => {
      if (!cancelled) setModel(homeScreenFromPayload(payload));
    }).catch(error => {
      if (!cancelled) {
        setTransportError(error?.message || 'Home could not be loaded from the server.');
      }
    });
    return () => { cancelled = true; };
  }, [transport]);

  return <Screen title="Home" subtitle="Your next episodes, progress and shelves">
    <SearchSlot
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}
    />
    <Section title="Now Playing" copy="Live playback and running check-ins in their Home row.">
      <PlaybackSlot onOpenDetail={() => navigate('Detail')} />
    </Section>
    {transportError ? <View style={styles.notice}>
      <Text accessibilityLiveRegion="polite" style={styles.noticeText}>{transportError}</Text>
    </View> : null}
    <HomeShelves
      groups={model.groups}
      deferredGroups={model.deferredGroups}
      showMediaTypeHeaders={model.showMediaTypeHeaders}
      labels={model.labels}
      palette={palette}
      readOnly={model.readOnly}
      itemWidth={168}
      onOpenCard={item => navigate('Detail', { item: item.card })}
      onOpenLink={(_href, item) => navigate('Detail', { item: item?.card })}
      onAction={(_action, item) => navigate('Detail', { item: item?.card })}
      onLoadRow={id => transport.loadRow({ rowId: id, limit: 14 })}
      onLoadMore={async row => {
        const page = await transport.loadRow({
          rowId: row.rowId,
          offset: row.loadedCount || 0,
          seed: row.seed,
          limit: 14,
        });
        return page ? mergeHomeRowPage(row, page) : null;
      }}
      onSortRow={row => transport.sortRow({ rowId: row.rowId })}
      onRefreshCovers={(ids, pending) => transport.refreshCovers({ ids, pending })} />
  </Screen>;
}

const styles = StyleSheet.create({
  notice: {
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.4)',
    borderRadius: radius.sm,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  noticeText: { color: '#f87171', fontSize: 13 },
});
