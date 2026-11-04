import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import { ListCard } from '../../../frontend/ui/ListCard';
import { Button } from '../../../frontend/ui/Button';
import { Badge } from '../../../frontend/ui/Badge';
import { palette, spacing } from '../theme';

const tiers = {
  id: 'TIERS',
  title: 'Tier boards',
  where: 'List detail tier view',
  note: 'Tier tiles, ordering and export will replace this note.',
};

const demoLists = [
  {
    id: '1',
    name: 'Weekend Watchlist',
    coverUrl: 'https://picsum.photos/seed/floppy-list-1/400/300',
    isSmart: false,
    visibility: 'Public',
    role: 'Owner',
    memberCount: 3,
    itemsCount: 12,
    completionPercent: 25,
    canEdit: true,
    href: '/demo/lists/1',
  },
  {
    id: '2',
    name: 'Sci-Fi Essentials',
    coverUrl: 'https://picsum.photos/seed/floppy-list-2/400/300',
    isSmart: true,
    visibility: 'Private',
    role: 'Owner',
    memberCount: 1,
    itemsCount: 8,
    completionPercent: 50,
    canEdit: true,
    href: '/demo/lists/2',
  },
  {
    id: '3',
    name: 'Shared with Friends',
    coverUrl: 'https://picsum.photos/seed/floppy-list-3/400/300',
    isSmart: false,
    visibility: 'Public',
    role: 'Collaborator',
    memberCount: 5,
    itemsCount: 24,
    completionPercent: 75,
    canEdit: false,
    href: '/demo/lists/3',
  },
];

const tags = ['All', 'Movies', 'Shows', 'Books', 'Games'];

export default function ListsScreen({ onBack, navigate }) {
  const [search, setSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState('All');
  const [loading, setLoading] = useState(false);

  const filtered = demoLists.filter((list) => {
    const matchesSearch = list.name.toLowerCase().includes(search.toLowerCase());
    const matchesTag = selectedTag === 'All' || list.tags?.includes(selectedTag);
    return matchesSearch && matchesTag;
  });

  return (
    <Screen title="Lists" subtitle="Curated, smart and shared collections" onBack={onBack}>
      <View style={styles.toolbar}>
        <Button label="Public Profile" tone="surface" onPress={() => {}} />
        <Button label="New List" tone="primary" onPress={() => {}} />
      </View>
      <TextInput
        style={styles.search}
        placeholder="Search lists..."
        value={search}
        onChangeText={setSearch}
        placeholderTextColor={palette.textMuted}
      />
      <View style={styles.tags}>
        {tags.map((tag) => (
          <Badge
            key={tag}
            label={tag}
            tone={tag === selectedTag ? 'indigo' : 'outline'}
            palette={{
              indigo: { color: '#fff', backgroundColor: palette.accentStrong },
              outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
            }}
            onPress={() => setSelectedTag(tag)}
          />
        ))}
      </View>
      {loading ? (
        <View style={styles.state}>
          <Text style={styles.stateText}>Loading lists…</Text>
        </View>
      ) : filtered.length === 0 ? (
        <View style={styles.state}>
          <Text style={styles.stateText}>No lists found.</Text>
          <Button label="Create Your First List" tone="primary" onPress={() => {}} />
        </View>
      ) : (
        <Section title="Your lists">
          <View style={styles.grid}>
            {filtered.map((list) => (
              <ListCard
                key={list.id}
                list={list}
                palette={palette}
                onOpen={() => navigate?.('ListDetail', { list })}
                onAction={(action) => {
                  if (action.title === 'Settings') {
                    // handle edit
                  }
                }}
              />
            ))}
          </View>
        </Section>
      )}
      <Section title="Tiers">
        <Note surface={tiers} />
      </Section>
    </Screen>
  );
}

const styles = StyleSheet.create({
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  search: {
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    borderRadius: 6,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    marginBottom: spacing.md,
  },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  state: { alignItems: 'center', gap: spacing.sm, padding: spacing.xl },
  stateText: { color: palette.textMuted, fontSize: 14 },
});
