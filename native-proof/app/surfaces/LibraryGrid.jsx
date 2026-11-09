import React from 'react';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MediaCard } from '../../../frontend/ui/MediaCard';
import { mediaCardPalette, spacing } from '../theme';
import { mediaCardModelFromRow } from '../data/libraryTransportCore';

export default function LibraryGrid({ rows = [], onOpen, onRate, selected = [], selecting = false, onToggle, groupBy = 'item' }) {
  const { width } = useWindowDimensions();
  const columns = width < 560 ? 2 : Math.min(5, Math.max(3, Math.floor((width + spacing.md) / 196)));
  const horizontalPadding = spacing.lg * 2;
  const cardWidth = (width - horizontalPadding - (columns - 1) * spacing.md) / columns;

  const buckets = new Map();
  rows.forEach(row => {
    const item = row.media?.item || {};
    const groupName = groupBy === 'series' ? item.provider_collection_name
      : groupBy === 'franchise' ? item.provider_franchise_name : '';
    const key = groupName || 'Ungrouped';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(row);
  });
  const groups = [...buckets.entries()];

  return <View style={styles.content}>
    {groups.map(([groupName, groupRows]) => <View key={groupName} style={styles.section}>
      {groupBy !== 'item' ? <Text style={styles.groupTitle}>{groupName}</Text> : null}
      <View style={styles.grid}>{groupRows.map(row => {
      const model = { ...mediaCardModelFromRow(row.media || row), identity: row.identity };
      const key = String(row.id);
      return <View key={key} style={{ width: cardWidth }}>
        <MediaCard
          model={model}
          labels={{ noStatus: 'No Status', rate: 'Rate' }}
          palette={mediaCardPalette}
          width={cardWidth}
          onOpen={() => selecting ? onToggle?.(key) : onOpen?.(row)}
          onRate={score => onRate?.(row, score)}
          selection={selecting ? {
            active: true,
            selected: selected.includes(key),
            label: `Select ${model.title}`,
            toggle: () => onToggle?.(key),
          } : undefined}
        />
      </View>;
      })}</View>
    </View>)}
  </View>;
}

const styles = StyleSheet.create({
  content: { gap: spacing.lg },
  section: { gap: spacing.sm },
  groupTitle: { color: mediaCardPalette.text, fontSize: 17, fontWeight: '700' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
});
