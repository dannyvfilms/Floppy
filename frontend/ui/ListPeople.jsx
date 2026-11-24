import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ArtworkImage } from './ArtworkImage';

/** People saved on a list, shown under its media. Props only: the platform
 * adapter supplies navigation and the remove request. */
export function ListPeople({ people = [], title = 'People', palette = {}, onOpen }) {
  if (!people.length) return null;
  const text = palette.text || '#fafafa';
  const muted = palette.textMuted || '#a1a1aa';
  return <View style={styles.root} accessibilityRole="summary">
    <Text role="heading" aria-level={2} style={[styles.title, { color: text }]}>{title}</Text>
    <View style={styles.grid}>
      {people.map(person => <View key={person.id} style={styles.tile}>
        <Pressable accessibilityRole="link" accessibilityLabel={person.name} onPress={() => onOpen?.(person)}>
          <ArtworkImage src={person.image} title={person.name} variant="poster" palette={palette}
            style={[styles.image, { backgroundColor: palette.surface || '#27272a' }]} />
          <Text numberOfLines={1} style={[styles.name, { color: text }]}>{person.name}</Text>
          {person.department ? <Text numberOfLines={1} style={[styles.department, { color: muted }]}>{person.department}</Text> : null}
        </Pressable>
      </View>)}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { marginTop: 32, gap: 16 },
  title: { fontSize: 20, fontWeight: '600' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  tile: { width: 104 },
  image: { width: 104, aspectRatio: 2 / 3, borderRadius: 8, overflow: 'hidden' },
  name: { marginTop: 8, fontSize: 14, fontWeight: '500' },
  department: { fontSize: 12 },
});
