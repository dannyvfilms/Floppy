import React, { useCallback, useMemo } from 'react';
import { AnimeSeasonsPageView } from '../../../frontend/pages/AnimeSeasonsPageView';
import { useAnimeSeasonsPage } from '../../../frontend/pages/useAnimeSeasonsPage';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { routeCardHref } from '../data/serverCardCore';
import { useMobileGridLayout } from '../data/useMobileGridLayout';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import { palette } from '../theme';

export const surface = {
  id: 'ANIME_SEASONS',
  status: 'in_progress',
  title: 'Anime Seasons: one MyAnimeList season as a card grid',
  where: 'Discover > Anime Seasons chip: heading with count, season stepper, Filters/Status/Sort toolbar, states and the card grid',
  note: 'The shared AnimeSeasonsPageView owns the heading, stepper, FilterBar toolbar and loading/empty/error states; the page model and each card model come from /api/v1/discover/anime-seasons/, built by the same server code as the web page. Cards are the shared MediaCard through MediaCardSlot, so Track and Add to lists open natively. Signed-out shows the error state. iOS and Android runtime interaction remain unverified.',
};

// A card model from the API, with the identity the native card actions need
// (the same adaptation the native search results make).
function gridItem(result) {
  const card = result.card || {};
  const identity = card.quickStatus?.identity;
  const model = identity ? { ...card, identity, actions: card.actions && {
    ...card.actions, items: card.actions.items.map(action => ({ ...action, media: identity })),
  } } : card;
  return { key: result.key, model };
}

export default function AnimeSeasonsScreen({ navigate }) {
  const auth = getActiveAuthSession();
  const request = useCallback((path, options) => (auth && typeof auth.request === 'function'
    ? auth.request(path, options)
    : Promise.reject(new Error('Sign in to your Floppy server to browse anime seasons.'))), [auth]);
  const season = useAnimeSeasonsPage({ request });
  const mobileGridLayout = useMobileGridLayout();
  const items = useMemo(() => (season.page?.results || []).map(gridItem), [season.page]);
  const openCard = model => {
    if (!routeCardHref(model?.href, navigate)) navigate('Detail', { item: model });
  };
  // The theme palette is a live object, so it is read on every render.
  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    <AnimeSeasonsPageView page={season.page} status={season.status} palette={{ ...palette, accentText: palette.accentContrast }}
      onChange={season.change} onStep={season.step} onRetry={season.retry}
      onOpenSettings={href => navigate('ProviderDetail', { slug: String(href).split('/').filter(Boolean).pop() })}
      content={<MediaCardSlot items={items} gridLayout="library" mobileGridLayout={mobileGridLayout}
        onOpenDetail={openCard} onOpenLink={href => { if (!routeCardHref(href, navigate)) navigate('Detail', { href }); }} />} />
  </Screen>;
}
