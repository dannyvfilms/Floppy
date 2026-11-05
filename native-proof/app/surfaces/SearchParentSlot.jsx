import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { ParentPicker } from '../../../frontend/ui/ParentPicker';
import { palette, radius, spacing } from '../theme';

const pickerPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  border: palette.border,
  accent: palette.accent,
  accentText: '#ffffff',
  danger: palette.danger,
  radius: radius.sm,
};

const tvShows = [
  { id: 'dune-prophecy', title: 'Dune: Prophecy', subtitle: 'TV Show · 2024' },
  { id: 'children-of-dune', title: 'Children of Dune', subtitle: 'TV Show · 2003' },
  { id: 'dune-2000', title: 'Dune', subtitle: 'TV Show · 2000' },
];

const seasons = [
  { id: 'prophecy-s1', title: 'Dune: Prophecy — Season 1', subtitle: '6 episodes · 2024' },
  { id: 'children-s1', title: 'Children of Dune — Season 1', subtitle: '3 episodes · 2003' },
  { id: 'dune-2000-s1', title: 'Dune — Season 1', subtitle: '3 episodes · 2000' },
];

const albums = [
  { id: 'dune-ost', title: 'Dune (Original Motion Picture Soundtrack)', subtitle: 'Hans Zimmer · 2021' },
  { id: 'dune-sketchbook', title: 'The Dune Sketchbook', subtitle: 'Hans Zimmer · 2021' },
  { id: 'dune-two-ost', title: 'Dune: Part Two (Original Motion Picture Soundtrack)', subtitle: 'Hans Zimmer · 2024' },
];

function DemoParentPicker({ title, placeholder, rows }) {
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const needle = query.trim().toLowerCase();
  const filtered = rows.filter(row => (
    !needle
    || row.title.toLowerCase().includes(needle)
    || row.subtitle.toLowerCase().includes(needle)
  ));
  return <ParentPicker
    title={title}
    query={query}
    placeholder={placeholder}
    results={filtered}
    selectedId={selectedId}
    state={filtered.length ? 'ready' : 'empty'}
    labels={{ empty: 'No matches found.' }}
    palette={pickerPalette}
    onQueryChange={setQuery}
    onSelect={row => setSelectedId(row.id)}
  />;
}

export default function SearchParentSlot() {
  return <View style={styles.stack}>
    <DemoParentPicker
      title="Parent TV show"
      placeholder="Search for a TV show…"
      rows={tvShows}
    />
    <DemoParentPicker
      title="Parent season"
      placeholder="Search for a season…"
      rows={seasons}
    />
    <DemoParentPicker
      title="Music album"
      placeholder="Search for an album…"
      rows={albums}
    />
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: spacing.md },
});
