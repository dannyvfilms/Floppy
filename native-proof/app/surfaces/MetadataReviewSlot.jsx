import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'METADATA-REVIEW',
  status: 'in_progress',
  title: 'Episode ordering, provider moves and metadata remaps',
  where: 'Detail metadata panel, episode ordering, TV provider switch and match results',
  note: 'The shared review components are being ported; the slot will render the episode-order review, provider-move confirmation and remap/library-move choices.',
};

export default function MetadataReviewSlot() {
  return <Note surface={surface} />;
}