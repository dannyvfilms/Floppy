import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useWindowDimensions, View } from 'react-native';
import { shelfCardWidth } from '../../../frontend/ui/HomeShelves';
import WindowedRail from './WindowedRail';
import { SearchResults } from '../../../frontend/ui/SearchResults';
import { mergeSearchRowPage, onlineRowParams, searchRowParams } from '../../../frontend/ui/searchRows';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { createSearchTransport } from '../data/searchTransport';
import { enrichServerCard, musicCreateFromHref, routeCardHref } from '../data/serverCardCore';
import { useMobileGridLayout } from '../data/useMobileGridLayout';
import { palette } from '../theme';
import MediaCardSlot from './MediaCardSlot';

export const surface = {
  id: 'SEARCH-RESULTS',
  status: 'ported',
  title: 'Search results as Home shelves',
  where: 'Search results',
  note: 'Search results are Home\'s shelves: your library first, then one row per provider that has results, drawn by the shared SearchResults with Home\'s rail, card and card width (including the Mobile Grid preference). The rows come from the same server builder as the web page.',
};

// The server's rows are read the way the web page reads them: one request for the rows, and
// one per "load more". The Django search view reads the session; a token sign-in reads the
// same rows from the API.
const resultsPath = session => (session.authType === 'token' ? '/api/v1/search/results/' : '/search/results');

export default function SearchResultsSlot({ query = '', mediaType = 'all', onOpenDetail, navigate }) {
  const { width } = useWindowDimensions();
  const mobileGridLayout = useMobileGridLayout();
  const itemWidth = shelfCardWidth(width, mobileGridLayout);
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [view, setView] = useState({ state: 'loading', props: {} });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => subscribeAuthSession(setSession), []);

  useEffect(() => {
    const trimmed = String(query || '').trim();
    if (!trimmed) {
      setView({ state: 'empty', props: { empty: { title: 'Search your library', body: 'Type something to search your library and your providers.' } } });
      return undefined;
    }
    if (!session || typeof session.request !== 'function') {
      setView({ state: 'empty', props: { empty: { title: 'Sign in to search', body: 'Connect your Floppy server to search your library.' } } });
      return undefined;
    }
    let cancelled = false;
    setView({ state: 'loading', props: {} });
    session.request(resultsPath(session), { query: { q: trimmed, media_type: mediaType } })
      .then(payload => { if (!cancelled) setView({ state: payload.state || 'ready', props: payload }); })
      .catch(() => { if (!cancelled) setView({ state: 'error', props: {} }); });
    return () => { cancelled = true; };
  }, [session, query, mediaType, attempt]);

  const onLoadMore = useCallback(async row => {
    const payload = await session.request(resultsPath(session), {
      query: searchRowParams(row, { query: String(query).trim(), mediaType }),
    });
    return payload.row ? mergeSearchRowPage(row, payload.row) : null;
  }, [session, query, mediaType]);

  const onLoadOnlineRow = useCallback(source => session.request(resultsPath(session), {
    query: onlineRowParams(source, { query: String(query).trim(), mediaType }),
  }), [session, query, mediaType]);

  const transport = useMemo(() => createSearchTransport(session ? { auth: session } : {}), [session]);
  const [creating, setCreating] = useState(false);

  const openCard = useCallback(async item => {
    const card = item?.card;
    // Online music artists and albums are created from the provider id first.
    const create = musicCreateFromHref(card?.href);
    if (create && navigate) {
      setCreating(true);
      try {
        const made = await transport.createMusic(create);
        navigate('Music', { artistId: made.artist_id, ...(made.album_id ? { albumId: made.album_id } : {}) });
      } catch {
        setView({ state: 'error', props: { labels: { errorBody: 'Could not add this entry.' } } });
      } finally {
        setCreating(false);
      }
      return;
    }
    if (!navigate || !routeCardHref(card?.href, navigate)) onOpenDetail?.(card);
  }, [onOpenDetail, navigate, transport]);

  // Each result is its own one-card host, so Track, Lists and rating open in place as on Home.
  const renderCard = useCallback(item => <View style={{ width: itemWidth }}><MediaCardSlot
    gridLayout="library"
    cardWidth={itemWidth}
    items={[{ key: String(item.id), model: enrichServerCard(item.card) }]}
    onOpenDetail={() => openCard(item)}
    onOpenLink={href => { if (!navigate || !routeCardHref(href, navigate)) openCard(item); }} /></View>,
  [navigate, openCard, itemWidth]);

  return <SearchResults
    {...view.props}
    state={creating ? 'loading' : view.state}
    palette={palette}
    itemWidth={itemWidth}
    renderCard={renderCard}
    onOpenCard={openCard}
    onOpenLink={(_href, item) => openCard(item)}
    onAction={(_action, item) => openCard(item)}
    railComponent={WindowedRail}
    onLoadMore={onLoadMore}
    onLoadOnlineRow={onLoadOnlineRow}
    onRetry={() => setAttempt(current => current + 1)}
  />;
}
