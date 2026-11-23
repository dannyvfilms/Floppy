import React, { useCallback } from 'react';
import { ProgressPageView } from '../../../frontend/pages/ProgressPageView';
import { useProgressPage } from '../../../frontend/pages/useProgressPage';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { palette, progressDetailPalette } from '../theme';

export const surface = {
  id: 'PROGRESS',
  status: 'in_progress',
  title: 'Progress page: what is left to watch, show by show',
  where: 'Progress screen: Show finished and sort controls, totals line, show cards with season bars and next episode, and the shared progress dialog',
  note: 'The shared ProgressPageView and ProgressShowCard own the controls, totals, cards, season list and dialog; the list loads from /api/v1/progress/ and seasons and the dialog from /api/v1/media/tv/<source>/<id>/progress-card/. Signed-out shows the retry state. Browser, iOS and Android runtime interaction remain unverified, so the surface stays in progress.',
};

export default function ProgressScreen({ navigate }) {
  const auth = getActiveAuthSession();
  const request = useCallback((path, options) => (auth && typeof auth.request === 'function'
    ? auth.request(path, options)
    : Promise.reject(new Error('Sign in to your Floppy server to see your progress.'))), [auth]);
  const page = useProgressPage({ request });
  // The theme palettes are live objects, so they are read on every render.
  const themed = { ...palette, ...progressDetailPalette, accentText: palette.accentContrast };
  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    <ProgressPageView page={page} palette={themed}
      onOpenShow={row => navigate('Detail', { href: row.url })}
      onOpenEpisode={episode => navigate('Detail', { href: episode.href })}
      onOpenSeasonOrEpisode={href => navigate('Detail', { href })} />
  </Screen>;
}
