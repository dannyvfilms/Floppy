import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SET-CARDS',
  title: 'Media card layout editor',
  where: 'Settings media cards per-type line selection, order and preview',
  status: 'in_progress',
  note: 'Per-media-type card lines, visibility and title options are being ported to the shared React Native editor with a live preview.',
};

export default function CardsSettingsSlot() {
  return <Note surface={surface} />;
}
