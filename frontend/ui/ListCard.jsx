import React from 'react';
import { View } from 'react-native';
import { MediaCard } from './MediaCard';

// Maps a list hub record onto the shared media-card model. The card keeps the
// shared artwork, badge and action behaviour; the list-specific metadata arrives
// as corner chips and a metadata line so the presentation stays in one place.
export function ListCard({ list, palette, width = 240, onOpen, onAction }) {
  const model = {
    title: list.name,
    image: { src: list.coverUrl, fallback: '', source: 'primary' },
    shape: 'landscape',
    video: false,
    href: list.href,
    statusChip: null,
    cornerChips: [],
    lines: [
      {
        join: 'plain',
        parts: [
          { text: `${list.itemsCount} ${list.itemsCount === 1 ? 'item' : 'items'}` },
          ...(list.completionPercent != null
            ? [{ text: ` • ${list.completionPercent}% completed`, muted: true }]
            : []),
        ],
      },
      ...((list.isSmart || (list.source && list.source !== 'local') || list.visibility || list.role || list.memberCount > 1)
        ? [{
            join: 'plain',
            parts: [
              ...(list.isSmart ? [{ text: 'Smart', muted: true }] : []),
              ...(list.isSmart && (list.source && list.source !== 'local') ? [{ text: ' • ', muted: true }] : []),
              ...(list.source && list.source !== 'local' ? [{ text: list.sourceLabel || list.source, muted: true }] : []),
              ...((list.isSmart || (list.source && list.source !== 'local')) && (list.visibility || list.role || list.memberCount > 1) ? [{ text: ' • ', muted: true }] : []),
              ...(list.visibility ? [{ text: list.visibilityLabel || (list.visibility === 'public' ? 'Public' : list.visibility === 'unlisted' ? 'Unlisted' : list.visibility === 'private' ? 'Private' : list.visibility) }] : []),
              ...(list.visibility && (list.role || list.memberCount > 1) ? [{ text: ' • ', muted: true }] : []),
              ...(list.role ? [{ text: list.role }] : []),
              ...(list.role && list.memberCount > 1 ? [{ text: ' • ', muted: true }] : []),
              ...(list.memberCount > 1 ? [{ text: `${list.memberCount} members`, muted: true }] : []),
            ],
          }]
        : []),
    ],
    rating: list.rating,
    actions: list.canEdit
      ? {
          href: null,
          items: [
            { kind: 'link', tone: 'indigo', title: 'Settings', glyph: '⚙', href: `${list.href}/edit` },
          ],
          ordering: null,
          modals: {},
          csrfToken: '',
          clickable: true,
          title: list.name,
        }
      : null,
  };
  return (
    <View>
      <MediaCard
        model={model}
        palette={palette}
        width={width}
        onOpen={onOpen}
        onAction={onAction}
      />
    </View>
  );
}
