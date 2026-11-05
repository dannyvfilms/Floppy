import React from 'react';
import { Note } from '../components/Note';

export const surface = {
  id: 'SHELL',
  title: 'Application shell and navigation',
  where: 'Signed-in top bar, public header and mobile navigation',
  status: 'in_progress',
  note: 'The shared top bar, mobile menu overlay and public/auth navigation are being ported here.',
};

export default function ShellSlot() {
  return <Note surface={surface} />;
}
