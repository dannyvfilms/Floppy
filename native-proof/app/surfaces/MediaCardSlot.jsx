import React, { useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { MediaCardActionHost } from '../../../frontend/ui/MediaCardActionHost';
import { MediaCardView } from '../../../frontend/ui/MediaCardView';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { mediaCardPalette, spacing } from '../theme';

export const surface = {
  id: 'MEDIA-CARD',
  title: 'Media card',
  where: 'Home rails, Discover, Library, Search and List results',
  status: 'in_progress',
  note: 'Poster, square, landscape and row cards render the shared model with artwork fallback, chips, progress, rating, action overlay, touch/hover reveal and read-only/selectable states. The native action host is wired to explicit callbacks and is being extended with the shared Track and Lists form bodies; Discover writes, bulk selection store and runtime evidence are still outstanding.',
};

const labels = {
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
};

function actionsFor(title) {
  return {
    href: '/demo/library',
    items: [
      {
        kind: 'modal',
        modal: 'track',
        tone: 'indigo',
        title: 'Edit tracking',
        glyph: '✎',
        url: '/demo/track',
        vals: { return_url: '/demo/library' },
        target: '#track-demo',
      },
      {
        kind: 'modal',
        modal: 'lists',
        tone: 'emerald',
        title: 'Add to custom lists',
        glyph: '☰',
        url: '/demo/lists',
        vals: { return_url: '/demo/library' },
        target: '#lists-demo',
      },
      {
        kind: 'link',
        tone: 'amber',
        title: 'View your activity history',
        glyph: '◷',
        href: '/demo/history',
      },
    ],
    ordering: null,
    modals: { track: 'track-demo', lists: 'lists-demo' },
    csrfToken: '',
    clickable: true,
    title,
  };
}

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
      actions: actionsFor('The Quiet Orbit'),
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
      actions: actionsFor('Signal & Static'),
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
      actions: actionsFor('Building a Home Studio'),
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
      actions: null,
    },
  },
];

function actionGlyph(action) {
  if (action.kind === 'drag') return '≡';
  if (action.modal === 'track') return '✎';
  if (action.modal === 'lists') return '☰';
  if (action.vals?.action === 'planning') return '＋';
  if (action.vals?.action === 'dismiss') return '⦸';
  if (action.kind === 'link') return '◷';
  return '•';
}

function renderActionIcon(action) {
  return <Text accessible={false} style={styles.actionGlyph}>{actionGlyph(action)}</Text>;
}

function ActionBody({ action }) {
  if (!action) return null;
  if (action.modal === 'track') {
    return <Text style={styles.hostBody}>The native tracking form and its save transport are not ported yet. This host uses the same action contract as the web popup.</Text>;
  }
  if (action.modal === 'lists') {
    return <Text style={styles.hostBody}>List membership uses the shared popup contract. The native list transport is not ported yet.</Text>;
  }
  if (action.kind === 'post') {
    return <Text style={styles.hostBody}>Discover plan and hide use the existing server POST contract. The native write adapter is not ported yet.</Text>;
  }
  return <Text style={styles.hostBody}>This link is routed by the platform navigation adapter.</Text>;
}

export default function MediaCardSlot({ onOpenDetail }) {
  const { width } = useWindowDimensions();
  const [ratings, setRatings] = useState({});
  const [pendingAction, setPendingAction] = useState(null);
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

  return <>
    <View style={styles.grid}>
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
          onAction={setPendingAction}
          renderActionIcon={renderActionIcon}
          onRate={score => setRatings(current => ({ ...current, [item.key]: score }))}
          renderRating={({ value, label, scaleMax, palette, onSelect }) => <RatingStars
            scaleMax={scaleMax} value={value} label={label} onSelect={onSelect} palette={palette}
            renderStar={lit => <Text style={[styles.pickerStar, { color: lit ? palette.lit : palette.unlit }]}>★</Text>} />} />;
      })}
    </View>
    <MediaCardActionHost action={pendingAction} open={!!pendingAction} labels={labels}
      palette={mediaCardPalette} onClose={() => setPendingAction(null)}>
      <ActionBody action={pendingAction} />
    </MediaCardActionHost>
  </>;
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  pickerStar: { fontSize: 20 },
  actionGlyph: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  hostBody: { color: '#a1a1aa', fontSize: 13, lineHeight: 19 },
});
