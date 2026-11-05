import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'PLAYBACK',
  status: 'in_progress',
  title: 'Now Playing and check-in',
  where: 'Home playback card and detail check-in state',
  note: 'The shared playback card and check-in state are being ported. The Home row and detail controls remain server-owned until the shared presentation lands.',
};

export default function PlaybackSlot() {
  return <Note surface={surface} />;
}
