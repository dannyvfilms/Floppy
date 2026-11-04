import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';

const lists = {
  id: 'LISTS',
  title: 'Custom and smart lists',
  where: 'Lists hub, list detail and public profiles',
  note: 'List cards, membership popups, visibility controls and the list table will replace this note.',
};
const tiers = {
  id: 'TIERS',
  title: 'Tier boards',
  where: 'List detail tier view',
  note: 'Tier tiles, ordering and export will replace this note.',
};

export default function ListsScreen({ onBack }) {
  return <Screen title="Lists" subtitle="Curated, smart and shared collections" onBack={onBack}>
    <Section title="Your lists"><Note surface={lists} /></Section>
    <Section title="Tiers"><Note surface={tiers} /></Section>
  </Screen>;
}
