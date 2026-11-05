import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { MediaCard } from '../../../frontend/ui/MediaCard';
import { Rail } from '../../../frontend/ui/Rail';
import { Note } from '../components/Note';
import { mediaCardPalette, railPalette, spacing } from '../theme';

export const surface = {
  id: 'RAILS',
  title: 'Horizontal shelves and load more',
  where: 'Home rails, Discover, cast and recommendations',
  status: 'ported',
  note: 'The shared rail renders headings, collapse, arrows, horizontal scrolling, bounded load-more and item slots through renderItem. Shelves use the shared MediaCard with demo card models until transport-backed rails are wired on the native screens.',
};

const shelf = [
  { id: 'bear', title: 'The Bear', meta: 'S3 E4 · Hulu' },
  { id: 'dune', title: 'Dune: Part Two', meta: '2024 · Film' },
  { id: 'severance', title: 'Severance', meta: 'S2 E1 · Apple TV+' },
  { id: 'samurai', title: 'Blue Eye Samurai', meta: 'S1 E6 · Netflix' },
  { id: 'past-lives', title: 'Past Lives', meta: '2023 · Film' },
  { id: 'shrinking', title: 'Shrinking', meta: 'S2 E3 · Apple TV+' },
  { id: 'last-of-us', title: 'The Last of Us', meta: 'S1 E7 · Max' },
  { id: 'poor-things', title: 'Poor Things', meta: '2023 · Film' },
  { id: 'andor', title: 'Andor', meta: 'S2 E2 · Disney+' },
];

const recommendations = [
  { id: 'arrival', title: 'Arrival', meta: '2016 · Film' },
  { id: 'blade-runner', title: 'Blade Runner 2049', meta: '2017 · Film' },
  { id: 'children-of-men', title: 'Children of Men', meta: '2006 · Film' },
  { id: 'annihilation', title: 'Annihilation', meta: '2018 · Film' },
  { id: 'sicario', title: 'Sicario', meta: '2015 · Film' },
];

function railModel(item) {
  return {
    mediaType: 'movie',
    identity: { mediaType: 'movie', source: 'demo', mediaId: item.id, title: item.title },
    shape: 'poster',
    video: false,
    href: '',
    image: { src: null, fallback: '', source: 'primary' },
    title: item.title,
    altTitle: null,
    statusChip: null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: [{
      join: 'plain',
      parts: item.meta.split(' · ').map((text, index) => ({ text, muted: index > 0 })),
    }],
    rating: null,
    ratingEditable: false,
    actions: null,
  };
}

function RailCard({ item }) {
  return <MediaCard model={railModel(item)} palette={mediaCardPalette} width={132} readOnly />;
}

export default function RailsSlot() {
  const [visibleItems, setVisibleItems] = useState(shelf.slice(0, 6));
  const [direction, setDirection] = useState('desc');
  const [loadingMore, setLoadingMore] = useState(false);
  const loadTimer = useRef(null);
  const hasMore = visibleItems.length < shelf.length;
  const orderedItems = direction === 'asc' ? [...visibleItems].reverse() : visibleItems;

  useEffect(() => () => clearTimeout(loadTimer.current), []);

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    loadTimer.current = setTimeout(() => {
      setVisibleItems(current => shelf.slice(0, current.length + 3));
      setLoadingMore(false);
    }, 450);
  }

  function toggleDirection() {
    setDirection(current => (current === 'asc' ? 'desc' : 'asc'));
  }

  return <View style={styles.stack}>
    <Rail title="Next up" titleDetail="This week" summary="New episodes and saved films from your library."
      summaryInline="Recently added" direction={direction} onSort={toggleDirection}
      sortLabel="Toggle sort direction for Next up" items={orderedItems} itemWidth={132}
      renderItem={item => <RailCard item={item} />}
      onLoadMore={loadMore} hasMore={hasMore} loadingMore={loadingMore}
      total={shelf.length} loadedCount={visibleItems.length} loadingLabel="Loading more"
      emptyLabel="Nothing queued yet." accessibilityLabel="Next up • This week"
      scrollLeftLabel="Scroll left" scrollRightLabel="Scroll right" palette={railPalette} />
    <Rail title="Because you watched Dune" summary="Science fiction with patient, atmospheric worlds."
      items={recommendations} itemWidth={132} renderItem={item => <RailCard item={item} />}
      collapsible collapseLabel="Toggle recommendations" palette={railPalette}
      accessibilityLabel="Because you watched Dune"
      scrollLeftLabel="Scroll left" scrollRightLabel="Scroll right" />
    <Note surface={surface} compact />
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: spacing.lg },
});
