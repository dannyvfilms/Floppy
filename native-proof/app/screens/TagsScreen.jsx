import React, { useMemo, useState } from 'react';
import { TagsPageView } from '../../../frontend/pages/TagsPageView';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { Screen } from '../components/Screen';
import { palette } from '../theme';

export const surface = {
  id: 'TAGS',
  status: 'ported',
  title: 'Tag index with per-media counts and delete',
  where: 'Tags page; the assignment, bulk-tag and settings filter surfaces stay with TagManagement consumers',
  note: 'The tag index renders the shared TagsPageView composition, which owns the heading, sort control, tag rows and empty state for web and Expo. Native keeps local demo records until a tags transport exists; ownership and destructive writes remain server-enforced, and iOS/Android runtime verification is separate from the Expo compile check.',
};

const MEDIA_TYPES = [
  { key: 'movie', label: 'Movies' },
  { key: 'tv', label: 'Shows' },
  { key: 'anime', label: 'Anime' },
  { key: 'book', label: 'Books' },
  { key: 'game', label: 'Games' },
  { key: 'music', label: 'Music' },
  { key: 'podcast', label: 'Podcasts' },
];

const MEDIA_TYPE_BY_KEY = Object.fromEntries(MEDIA_TYPES.map(type => [type.key, type]));

const DEMO_TAGS = [
  { id: 'sci-fi', name: 'Sci-fi', counts: { movie: 10, tv: 9, book: 5, anime: 3 } },
  { id: 'favorite', name: 'Favorite', counts: { movie: 9, tv: 5, book: 4 } },
  { id: 'comfort', name: 'Comfort watches', counts: { tv: 7, movie: 4 } },
  { id: 'family', name: 'Family night', counts: { movie: 4, game: 3 } },
  { id: 'book-club', name: 'Book club', counts: { book: 6 } },
  { id: 'listen-again', name: 'Listen again', counts: { music: 4, podcast: 5 } },
  { id: 'world-cinema', name: 'World cinema', counts: { movie: 5 } },
  { id: 'cozy-games', name: 'Cozy games', counts: { game: 6 } },
  { id: 'anime-rewatch', name: 'Anime rewatch', counts: { anime: 4 } },
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
      count,
    }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

function indexTag(tag) {
  return {
    id: tag.id,
    name: tag.name,
    count: totalCount(tag),
    types: typeBreakdown(tag),
  };
}

export default function TagsScreen({ onBack }) {
  const [tags, setTags] = useState(DEMO_TAGS);
  const [sort, setSort] = useState('name');
  const [deleteTarget, setDeleteTarget] = useState(null);

  const indexedTags = useMemo(() => tags.map(indexTag), [tags]);
  const visibleTags = useMemo(() => [...indexedTags].sort((left, right) => sort === 'count'
    ? right.count - left.count || left.name.localeCompare(right.name)
    : left.name.localeCompare(right.name)), [indexedTags, sort]);

  function confirmDelete() {
    if (!deleteTarget) return;
    setTags(current => current.filter(tag => tag.id !== deleteTarget.id));
    setDeleteTarget(null);
  }

  return <Screen onBack={onBack}>
    <TagsPageView
      tags={visibleTags}
      sort={sort}
      palette={palette}
      onSortChange={setSort}
      onDelete={setDeleteTarget} />
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
