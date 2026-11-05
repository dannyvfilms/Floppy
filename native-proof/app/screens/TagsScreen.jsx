import React, { useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Screen, Section } from '../components/Screen';
import { Button } from '../../../frontend/ui/Button';
import {
  TagAssignmentDialog,
  TagBulkDialog,
  TagIndex,
  TagMediaFilter,
} from '../../../frontend/ui/TagManagement';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'TAGS',
  status: 'ported',
  title: 'Tag index, item assignment, bulk tagging and settings filters',
  where: 'Tags screen; shared by detail assignment, library bulk tagging and settings media-type filters',
  note: 'The tag index, search and sort, item assignment with add/remove/create, selected-item bulk add/remove, confirmed library-wide deletion and media-type filter semantics use shared React Native presentation with local demo state. The web tag index, detail tag modal, bulk toolbar and settings filters keep their server-rendered fallback; ownership and destructive writes remain server-enforced.',
};

const MEDIA_TYPES = [
  { key: 'movie', label: 'Movies', group: 'screen' },
  { key: 'tv', label: 'Shows', group: 'screen' },
  { key: 'anime', label: 'Anime', group: 'anime_manga' },
  { key: 'book', label: 'Books', group: 'reading' },
  { key: 'game', label: 'Games', group: 'games' },
  { key: 'music', label: 'Music', group: 'music' },
  { key: 'podcast', label: 'Podcasts', group: 'podcasts' },
];

const MEDIA_TYPE_BY_KEY = Object.fromEntries(MEDIA_TYPES.map(type => [type.key, type]));

const SETTINGS_GROUPS = [
  { key: 'screen', label: 'Movies & TV' },
  { key: 'anime_manga', label: 'Anime & Manga' },
  { key: 'reading', label: 'Books & Comics' },
  { key: 'games', label: 'Games' },
  { key: 'podcasts', label: 'Podcasts' },
  { key: 'music', label: 'Music' },
];

const DEMO_ITEMS = [
  { id: 'dune-2', title: 'Dune: Part Two', detail: 'Movie · 2024', mediaType: 'movie' },
  { id: 'shogun', title: 'Shōgun', detail: 'Show · 2024', mediaType: 'tv' },
  { id: 'piranesi', title: 'Piranesi', detail: 'Book · 2020', mediaType: 'book' },
];

const DEMO_TAGS = [
  { id: 'sci-fi', name: 'Sci-fi', owned: true, counts: { movie: 10, tv: 9, book: 5, anime: 3 } },
  { id: 'favorite', name: 'Favorite', owned: true, counts: { movie: 9, tv: 5, book: 4 } },
  { id: 'comfort', name: 'Comfort watches', owned: true, counts: { tv: 7, movie: 4 } },
  { id: 'family', name: 'Family night', owned: true, counts: { movie: 4, game: 3 } },
  { id: 'book-club', name: 'Book club', owned: true, counts: { book: 6 } },
  { id: 'listen-again', name: 'Listen again', owned: true, counts: { music: 4, podcast: 5 } },
  { id: 'world-cinema', name: 'World cinema', owned: true, counts: { movie: 5 } },
  { id: 'cozy-games', name: 'Cozy games', owned: true, counts: { game: 6 } },
  { id: 'anime-rewatch', name: 'Anime rewatch', owned: true, counts: { anime: 4 } },
];

function totalCount(tag) {
  return Object.values(tag.counts || {}).reduce((sum, count) => sum + count, 0);
}

function typeBreakdown(tag) {
  return Object.entries(tag.counts || {})
    .filter(([, count]) => count > 0)
    .map(([key, count]) => ({
      key,
      label: MEDIA_TYPE_BY_KEY[key]?.label || key,
      group: MEDIA_TYPE_BY_KEY[key]?.group || '',
      count,
    }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

function indexTag(tag) {
  return {
    id: tag.id,
    name: tag.name,
    owned: tag.owned !== false,
    count: totalCount(tag),
    types: typeBreakdown(tag),
  };
}

function adjustCount(tag, mediaType, delta) {
  const nextCount = Math.max(0, (tag.counts?.[mediaType] || 0) + delta);
  const counts = { ...(tag.counts || {}) };
  if (nextCount > 0) counts[mediaType] = nextCount;
  else delete counts[mediaType];
  return { ...tag, counts };
}

export default function TagsScreen({ onBack }) {
  const [tags, setTags] = useState(DEMO_TAGS);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('name');
  const [mediaGroup, setMediaGroup] = useState('all');
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [assignmentError, setAssignmentError] = useState('');
  const [itemTagIds, setItemTagIds] = useState(() => new Set(['sci-fi', 'favorite']));
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkTag, setBulkTag] = useState('');
  const [bulkAction, setBulkAction] = useState('add');
  const [bulkError, setBulkError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [notice, setNotice] = useState('');

  const item = DEMO_ITEMS[0];

  const indexedTags = useMemo(() => tags.map(indexTag), [tags]);

  const filteredTags = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const visible = indexedTags.filter(tag => {
      const matchesQuery = !needle || tag.name.toLowerCase().includes(needle);
      const matchesGroup = mediaGroup === 'all' || tag.types.some(type => type.group === mediaGroup);
      return matchesQuery && matchesGroup;
    });
    return visible.sort((left, right) => sort === 'count'
      ? right.count - left.count || left.name.localeCompare(right.name)
      : left.name.localeCompare(right.name));
  }, [indexedTags, mediaGroup, query, sort]);

  const assignmentTags = useMemo(() => tags.map(tag => ({
    ...tag,
    count: totalCount(tag),
    hasTag: itemTagIds.has(tag.id),
  })), [itemTagIds, tags]);

  const appliedNames = tags.filter(tag => itemTagIds.has(tag.id)).map(tag => tag.name);

  function toggleItemTag(tag) {
    if (tag.owned === false) {
      setAssignmentError('Only the owner of a tag can change it.');
      return;
    }
    const adding = !itemTagIds.has(tag.id);
    setItemTagIds(current => {
      const next = new Set(current);
      if (adding) next.add(tag.id);
      else next.delete(tag.id);
      return next;
    });
    setTags(current => current.map(entry => entry.id === tag.id
      ? adjustCount(entry, item.mediaType, adding ? 1 : -1)
      : entry));
    setAssignmentError('');
    setNotice(`"${tag.name}" ${adding ? 'added to' : 'removed from'} ${item.title} in this demo.`);
  }

  function createItemTag(name) {
    const value = name.trim();
    if (!value) {
      setAssignmentError('Enter a tag name.');
      return false;
    }
    if (tags.some(tag => tag.name.toLowerCase() === value.toLowerCase())) {
      setAssignmentError(`Tag "${value}" already exists.`);
      return false;
    }
    const id = `tag-${Date.now()}`;
    setTags(current => [...current, { id, name: value, owned: true, counts: { [item.mediaType]: 1 } }]);
    setItemTagIds(current => new Set([...current, id]));
    setNotice(`"${value}" was created and applied to ${item.title} in this demo.`);
    setAssignmentError('');
    return true;
  }

  function requestDelete(tag) {
    if (tag.owned === false) {
      setNotice('Only the owner of a tag can delete it.');
      return;
    }
    setDeleteTarget(tag);
  }

  function deleteTag(tag) {
    const name = tag.name;
    setTags(current => current.filter(entry => entry.id !== tag.id));
    setItemTagIds(current => {
      const next = new Set(current);
      next.delete(tag.id);
      return next;
    });
    if (bulkTag === name) setBulkTag('');
    setNotice(`"${name}" was deleted from every item in this demo.`);
  }

  function confirmDelete() {
    if (!deleteTarget) return;
    deleteTag(deleteTarget);
    setDeleteTarget(null);
  }

  function openBulk() {
    setBulkTag('');
    setBulkAction('add');
    setBulkError('');
    setBulkOpen(true);
  }

  function applyBulkTag() {
    if (!bulkTag) {
      setBulkError('Choose a tag.');
      return;
    }
    const target = tags.find(tag => tag.name === bulkTag);
    if (!target || target.owned === false) {
      setBulkError('Only the owner of a tag can change it.');
      return;
    }
    setTags(current => current.map(tag => {
      if (tag.id !== target.id) return tag;
      return DEMO_ITEMS.reduce((next, entry) =>
        adjustCount(next, entry.mediaType, bulkAction === 'add' ? 1 : -1), tag);
    }));
    if (DEMO_ITEMS[0].id === item.id) {
      setItemTagIds(current => {
        const next = new Set(current);
        if (bulkAction === 'add') next.add(target.id);
        else next.delete(target.id);
        return next;
      });
    }
    const count = DEMO_ITEMS.length;
    setBulkOpen(false);
    setNotice(`"${bulkTag}" was ${bulkAction === 'add' ? 'added to' : 'removed from'} ${count} selected items in this demo.`);
  }

  function openType(tag, type) {
    setNotice(`Opens ${type.label} filtered by "${tag.name}" through the platform navigation adapter.`);
  }

  return <Screen title="Tags" subtitle="All tags you've created, with how many items use each one" onBack={onBack}>
    <View style={styles.toolbar}>
      <Text style={styles.toolbarCopy}>Counts describe the whole library and stay global while you search or filter.</Text>
      <Button label="Bulk tag selected items" tone="surface" onPress={openBulk} />
    </View>
    {notice ? <Text accessibilityRole="status" style={styles.notice}>{notice}</Text> : null}

    <Section title="Library tags" copy="Search and sort your tags. Media-type filters use the same groups as Settings.">
      <TagMediaFilter
        options={SETTINGS_GROUPS}
        active={mediaGroup}
        allLabel="All"
        prompt="Browse by media type:"
        palette={palette}
        onSelect={setMediaGroup} />
      <TagIndex
        tags={filteredTags}
        sort={sort}
        query={query}
        palette={palette}
        emptyText={indexedTags.length ? 'No tags match this search or filter.' : 'No tags yet. Add tags to items from their detail page to see them here.'}
        onQueryChange={setQuery}
        onSortChange={setSort}
      onDelete={deleteTag}
        onOpenType={openType} />
    </Section>

    <Section title="Assign to an item" copy="A tag can be added to or removed from one item without changing the others.">
      <View style={styles.itemCard}>
        <View style={styles.itemBody}>
          <Text style={styles.itemTitle}>{item.title}</Text>
          <Text style={styles.itemDetail}>{item.detail} · tmdb</Text>
          <Text style={styles.itemTags}>
            {appliedNames.length ? appliedNames.join(', ') : 'No tags applied'}
          </Text>
        </View>
        <Button label="Manage tags" onPress={() => {
          setAssignmentError('');
          setAssignmentOpen(true);
        }} />
      </View>
    </Section>

    <Section title="Bulk tagging" copy="Add or remove one tag across a selected set of items. Each selected item keeps its own identity.">
      <View style={styles.bulkCard}>
        <Text style={styles.bulkTitle}>{`${DEMO_ITEMS.length} selected items`}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.bulkRow}>
          {DEMO_ITEMS.map(entry => <View key={entry.id} style={styles.bulkItem}>
            <Text numberOfLines={1} style={styles.bulkItemTitle}>{entry.title}</Text>
            <Text style={styles.bulkItemDetail}>{entry.detail}</Text>
          </View>)}
        </ScrollView>
        <View style={styles.bulkActions}>
          <Button label="Apply tag" onPress={openBulk} />
          <Button label="Clear selection" tone="surface"
            onPress={() => setNotice('Selection is cleared in this demo.')} />
        </View>
      </View>
    </Section>

    <TagAssignmentDialog
      open={assignmentOpen}
      item={{ title: item.title, subtitle: item.detail }}
      tags={assignmentTags}
      palette={palette}
      error={assignmentError}
      onToggle={toggleItemTag}
      onCreate={createItemTag}
      onDelete={requestDelete}
      onClose={() => setAssignmentOpen(false)} />

    <TagBulkDialog
      open={bulkOpen}
      selectedItems={DEMO_ITEMS}
      tags={tags.map(tag => ({ id: tag.id, name: tag.name, owned: tag.owned, count: totalCount(tag) }))}
      selectedTag={bulkTag}
      action={bulkAction}
      error={bulkError}
      palette={palette}
      onSelectTag={setBulkTag}
      onActionChange={setBulkAction}
      onApply={applyBulkTag}
      onClose={() => setBulkOpen(false)} />

    <ConfirmDialog
      visible={!!deleteTarget}
      title="Delete tag"
      message={deleteTarget ? `Delete the "${deleteTarget.name}" tag from your library? This removes it from every item.` : ''}
      warning={deleteTarget ? 'This removes the tag from every item that uses it.' : ''}
      confirmLabel="Delete tag"
      cancelLabel="Keep tag"
      palette={palette}
      onCancel={() => setDeleteTarget(null)}
      onConfirm={confirmDelete} />
  </Screen>;
}

const styles = StyleSheet.create({
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  toolbarCopy: { flexShrink: 1, color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  notice: { color: palette.textSecondary, fontSize: 12, lineHeight: 17 },
  itemCard: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: spacing.md, borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.md },
  itemBody: { flexShrink: 1, gap: 2 },
  itemTitle: { color: palette.text, fontSize: 16, fontWeight: '600' },
  itemDetail: { color: palette.textMuted, fontSize: 12 },
  itemTags: { color: palette.textSecondary, fontSize: 12, lineHeight: 17 },
  bulkCard: { gap: spacing.md, borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.md },
  bulkTitle: { color: palette.text, fontSize: 15, fontWeight: '600' },
  bulkRow: { flexDirection: 'row', gap: spacing.sm },
  bulkItem: { width: 180, borderWidth: 1, borderColor: palette.border, borderRadius: radius.sm, backgroundColor: palette.surfaceStrong, padding: spacing.sm, gap: 2 },
  bulkItemTitle: { color: palette.text, fontSize: 13, fontWeight: '600' },
  bulkItemDetail: { color: palette.textMuted, fontSize: 11 },
  bulkActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
