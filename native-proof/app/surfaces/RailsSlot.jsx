import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Rail } from '../../../frontend/ui/Rail';
import { Note } from '../components/Note';
import { palette, radius, railPalette, spacing } from '../theme';

export const surface = {
  id: 'RAILS',
  title: 'Horizontal shelves and load more',
  where: 'Home rails, Discover, cast and recommendations',
  status: 'ported',
  note: 'The shared rail renders headings, collapse, arrows, horizontal scrolling, bounded load-more and item slots through renderItem. Demo tiles stand in for the unported media card.',
};

const shelf = [
  { id: 'bear', title: 'The Bear', meta: 'S3 E4 · Hulu', color: '#3f3f46' },
  { id: 'dune', title: 'Dune: Part Two', meta: '2024 · Film', color: '#7c2d12' },
  { id: 'severance', title: 'Severance', meta: 'S2 E1 · Apple TV+', color: '#1e3a8a' },
  { id: 'samurai', title: 'Blue Eye Samurai', meta: 'S1 E6 · Netflix', color: '#831843' },
  { id: 'past-lives', title: 'Past Lives', meta: '2023 · Film', color: '#365314' },
  { id: 'shrinking', title: 'Shrinking', meta: 'S2 E3 · Apple TV+', color: '#4c1d95' },
  { id: 'last-of-us', title: 'The Last of Us', meta: 'S1 E7 · Max', color: '#14532d' },
  { id: 'poor-things', title: 'Poor Things', meta: '2023 · Film', color: '#9a3412' },
  { id: 'andor', title: 'Andor', meta: 'S2 E2 · Disney+', color: '#374151' },
];

const recommendations = [
  { id: 'arrival', title: 'Arrival', meta: '2016 · Film', color: '#1e40af' },
  { id: 'blade-runner', title: 'Blade Runner 2049', meta: '2017 · Film', color: '#7c2d12' },
  { id: 'children-of-men', title: 'Children of Men', meta: '2006 · Film', color: '#374151' },
  { id: 'annihilation', title: 'Annihilation', meta: '2018 · Film', color: '#14532d' },
  { id: 'sicario', title: 'Sicario', meta: '2015 · Film', color: '#78350f' },
];

function DemoPoster({ item }) {
  return <View style={styles.item} accessible accessibilityLabel={`${item.title}, ${item.meta}`}>
    <View accessibilityRole="image" accessibilityLabel={`${item.title} artwork`} style={[styles.poster, { backgroundColor: item.color }]}>
      <Text aria-hidden style={styles.posterLetter}>{item.title.slice(0, 1)}</Text>
    </View>
    <Text numberOfLines={2} style={styles.itemTitle}>{item.title}</Text>
    <Text numberOfLines={1} style={styles.itemMeta}>{item.meta}</Text>
  </View>;
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
      renderItem={item => <DemoPoster item={item} />}
      onLoadMore={loadMore} hasMore={hasMore} loadingMore={loadingMore}
      total={shelf.length} loadedCount={visibleItems.length} loadingLabel="Loading more"
      emptyLabel="Nothing queued yet." accessibilityLabel="Next up • This week"
      scrollLeftLabel="Scroll left" scrollRightLabel="Scroll right" palette={railPalette} />
    <Rail title="Because you watched Dune" summary="Science fiction with patient, atmospheric worlds."
      items={recommendations} itemWidth={132} renderItem={item => <DemoPoster item={item} />}
      collapsible collapseLabel="Toggle recommendations" palette={railPalette}
      accessibilityLabel="Because you watched Dune"
      scrollLeftLabel="Scroll left" scrollRightLabel="Scroll right" />
    <Note surface={surface} compact />
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: spacing.lg },
  item: { gap: 4 },
  poster: { width: '100%', aspectRatio: 2 / 3, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  posterLetter: { color: palette.textSecondary, fontSize: 30, fontWeight: '700' },
  itemTitle: { color: palette.text, fontSize: 12, fontWeight: '600', lineHeight: 16 },
  itemMeta: { color: palette.textMuted, fontSize: 11, lineHeight: 14 },
});
