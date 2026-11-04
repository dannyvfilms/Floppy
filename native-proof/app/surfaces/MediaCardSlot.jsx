import React, { useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { MediaCardView } from '../../../frontend/ui/MediaCardView';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { mediaCardPalette, spacing } from '../theme';

export const surface = {
  id: 'MEDIA-CARD',
  title: 'Media card',
  where: 'Home rails, Discover, Library, Search and List results',
  status: 'in_progress',
  note: 'Poster, square, landscape and row cards render the shared model with artwork fallback, chips, progress, rating and read-only states. The web-only action layer is still being ported.',
};

const labels = {
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
};

const demoItems = [
  {
    key: 'quiet-orbit',
    model: {
      mediaType: 'tv',
      shape: 'poster',
      video: false,
      href: '/demo/the-quiet-orbit',
      image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
      title: 'The Quiet Orbit',
      altTitle: null,
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [{ kind: 'next-episode', text: 'Next ep', href: '/demo/the-quiet-orbit/next' }],
      titleLinks: [],
      progressBar: { percent: 62, paused: false },
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• 6 / 10 episodes', muted: true }] }],
      rating: { label: '8.0', value: 8, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: true,
    },
  },
  {
    key: 'signal-static',
    model: {
      mediaType: 'podcast',
      shape: 'square',
      video: false,
      href: '/demo/signal-and-static',
      image: { src: 'https://picsum.photos/seed/floppy-signal/400/400', fallback: '', source: 'primary' },
      title: 'Signal & Static',
      altTitle: 'Signal and Static',
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [],
      titleLinks: [],
      progressBar: { percent: 38, paused: true },
      lines: [{ join: 'plain', parts: [{ text: '2023' }, { text: '• 3 / 8 episodes', muted: true }] }],
      rating: { label: '4.5', value: 4.5, scaleMax: 5, rateLabel: 'Rate' },
      ratingEditable: true,
    },
  },
  {
    key: 'home-studio',
    model: {
      mediaType: 'video',
      shape: 'landscape',
      video: true,
      href: '/demo/building-a-home-studio',
      image: { src: 'https://picsum.photos/seed/floppy-studio/800/450', fallback: '', source: 'primary' },
      title: 'Building a Home Studio',
      altTitle: null,
      statusChip: { kind: 'status', status: 'Completed', hideOnMobile: false },
      cornerChips: [{ kind: 'runtime', text: '12:40' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• Watched', muted: true }] }],
      rating: null,
      ratingEditable: true,
    },
  },
  {
    key: 'paper-lanterns',
    model: {
      mediaType: 'book',
      shape: 'poster',
      video: false,
      publicView: true,
      href: '/demo/paper-lanterns',
      image: { src: null, fallback: '', source: 'primary' },
      title: 'Paper Lanterns',
      altTitle: null,
      statusChip: {
        kind: 'media-type',
        type: 'book',
        style: 'soft',
        color: '#D946EF',
        contrast: '#FFFFFF',
        label: 'Book',
      },
      cornerChips: [{ kind: 'collected', text: '4/8 collected', title: '4 of 8 episodes collected' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2022' }, { text: '• 0 / 320 pages', muted: true }] }],
      rating: { label: '6.5', value: 6.5, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: false,
    },
  },
];

export default function MediaCardSlot({ onOpenDetail }) {
  const { width } = useWindowDimensions();
  const [ratings, setRatings] = useState({});
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

  return <View style={styles.grid}>
    {demoItems.map(item => {
      const value = ratings[item.key];
      const model = value === undefined ? item.model : {
        ...item.model,
        rating: item.model.rating && {
          ...item.model.rating,
          value,
          label: value == null ? null : String(value),
        },
      };
      return <MediaCardView key={item.key} model={model} labels={labels} palette={mediaCardPalette}
        width={cardWidth} onOpen={onOpenDetail}
        onOpenLink={onOpenDetail}
        onRate={score => setRatings(current => ({ ...current, [item.key]: score }))}
        renderRating={({ value, label, scaleMax, palette, onSelect }) => <RatingStars
          scaleMax={scaleMax} value={value} label={label} onSelect={onSelect} palette={palette}
          renderStar={lit => <Text style={[styles.pickerStar, { color: lit ? palette.lit : palette.unlit }]}>★</Text>} />} />;
    })}
  </View>;
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  pickerStar: { fontSize: 20 },
});
