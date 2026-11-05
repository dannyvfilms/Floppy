import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { DetailRelated } from '../../../frontend/ui/DetailRelated';
import { mediaCardPalette, spacing } from '../theme';

export const surface = {
  id: 'DETAIL-RELATED',
  status: 'ported',
  title: 'Related media and Steam DLCs',
  where: 'Game, movie, show, book and comic detail pages',
  note: 'The shared DetailRelated renders IGDB DLC, expansion and remake card sections with tracked status and ratings, the show-more control, section labels, and display-only Steam DLC links with titles, images and store URLs. The web detail keeps its server fallback and mounts the same presentation over it.',
};

const labels = {
  showMore: 'Show more',
  showLess: 'Show less',
  dlcs: 'DLCs',
  empty: 'No related media available.',
  loading: 'Loading related media…',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
};

function card(key, title, href, image, overrides = {}) {
  return {
    key,
    model: {
      cardKey: key,
      mediaType: 'game',
      shape: 'poster',
      href,
      image: { src: image, fallback: '', source: 'primary' },
      title,
      altTitle: null,
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2025' }, { text: '· DLC', muted: true }] }],
      rating: { label: '8', value: 8, scaleMax: 10, rateLabel: 'Rate', rateUrl: '' },
      ratingEditable: true,
      actions: null,
      ...overrides,
    },
  };
}

const initialSections = [
  {
    id: 'dlcs',
    label: 'DLCs',
    items: [
      card('outer-ring', 'The Quiet Orbit: Outer Ring', '/demo/games/quiet-orbit/outer-ring',
        'https://picsum.photos/seed/floppy-dlc-outer/400/600'),
      card('halcyon', 'The Quiet Orbit: Halcyon', '/demo/games/quiet-orbit/halcyon',
        'https://picsum.photos/seed/floppy-dlc-halcyon/400/600', {
          statusChip: { kind: 'status', status: 'Completed', hideOnMobile: false },
          rating: { label: '9', value: 9, scaleMax: 10, rateLabel: 'Rate', rateUrl: '' },
        }),
      card('signal', 'The Quiet Orbit: Signal Lost', '/demo/games/quiet-orbit/signal',
        'https://picsum.photos/seed/floppy-dlc-signal/400/600', {
          statusChip: null,
          rating: null,
        }),
    ],
  },
  {
    id: 'standalone_expansions',
    label: 'Standalone Expansions',
    items: [
      card('drift', 'Drift', '/demo/games/drift',
        'https://picsum.photos/seed/floppy-expansion-drift/400/600', {
          statusChip: { kind: 'status', status: 'Planning', hideOnMobile: false },
          rating: null,
        }),
    ],
  },
  {
    id: 'remakes',
    label: 'Remakes',
    items: [
      card('relay', 'The Quiet Orbit: Relay Edition', '/demo/games/quiet-orbit/relay',
        'https://picsum.photos/seed/floppy-remake-relay/400/600'),
    ],
  },
];

const steamDlcs = [
  {
    title: 'The Quiet Orbit Soundtrack',
    image: 'https://picsum.photos/seed/floppy-steam-soundtrack/460/215',
    url: 'https://store.steampowered.com/',
  },
  {
    title: 'The Quiet Orbit Art Book',
    image: 'https://picsum.photos/seed/floppy-steam-artbook/460/215',
    url: 'https://store.steampowered.com/',
  },
];

export default function DetailRelatedSlot({ onOpenExternal }) {
  const [sections, setSections] = useState(initialSections);

  function rate(model, score) {
    setSections(current => current.map(section => ({
      ...section,
      items: section.items.map(item => item.key === model.cardKey
        ? {
          ...item,
          model: {
            ...item.model,
            rating: { ...item.model.rating, value: score, label: score == null ? null : String(score) },
          },
        }
        : item),
    })));
  }

  return <View style={styles.root}>
    <DetailRelated
      model={{ sections, steamDlcs }}
      labels={labels}
      palette={mediaCardPalette}
      onOpen={() => {}}
      onRate={rate}
      onOpenExternal={onOpenExternal} />
  </View>;
}

const styles = StyleSheet.create({
  root: { width: '100%', gap: spacing.lg },
});
