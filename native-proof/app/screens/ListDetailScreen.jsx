import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import { ListHeader } from '../../../frontend/ui/ListHeader';
import { palette } from '../theme';

const listDetail = {
  id: 'LIST-DETAIL',
  title: 'List detail',
  where: 'List detail page',
  status: 'in_progress',
  note: 'The result grid, table and membership/visibility popup are being ported; this screen still renders only the header.',
};

export default function ListDetailScreen({ params, onBack }) {
  const list = params?.list || {
    name: 'List',
    itemsCount: 0,
    completionPercent: null,
    visibility: 'private',
    memberCount: 1,
    canEdit: false,
  };
  return (
    <Screen title={list.name} subtitle="List detail" onBack={onBack}>
      <ListHeader
        list={list}
        palette={palette}
        onAddItem={() => {}}
        onExport={() => {}}
        onMore={() => {}}
        onEdit={() => {}}
      />
      <Section title="Items">
        <Note surface={listDetail} />
      </Section>
    </Screen>
  );
}
