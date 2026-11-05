import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'ARTWORK',
  status: 'in_progress',
  title: 'Cover and edition selection',
  where: 'Detail and tracking metadata for library items',
  note: 'The cover picker and edition picker are being moved to shared React Native presentation. Candidate, file, link, preview, reset, save and return behavior stays shared; platform file, drag, camera and caching stay in adapters.',
};

export default function ArtworkSlot() {
  return <Note surface={surface} />;
}
