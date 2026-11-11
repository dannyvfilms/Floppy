import React, { useCallback, useEffect, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { shelfCardWidth } from '../../../frontend/ui/HomeShelves';
import WindowedRail from './WindowedRail';
import { SearchResults } from '../../../frontend/ui/SearchResults';
import { mergeSearchRowPage, onlineRowParams, searchRowParams } from '../../../frontend/ui/searchRows';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { useMobileGridLayout } from '../data/useMobileGridLayout';
import { palette } from '../theme';

export const surface = {
  id: 'SEARCH-RESULTS',
  status: 'ported',
  title: 'Search results as Home shelves',
  where: 'Search results',
  note: 'Search results are Home\'s shelves: your library first, then one row per provider that has results, drawn by the shared SearchResults with Home\'s rail, card and card width (including the Mobile Grid preference). The rows come from the same server builder as the web page.',
};

// The server's rows are read the way the web page reads them: one request for the rows, and
// one per "load more". The Django search view reads the session, so a token sign-in cannot.
export default function SearchResultsSlot({ query = '', mediaType = 'all', onOpenDetail }) {
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
    if (session.authType === 'token') {
      setView({ state: 'error', props: { labels: { errorBody: 'Search results need a password sign-in.' } } });
      return undefined;
    }
    let cancelled = false;
    setView({ state: 'loading', props: {} });
    session.request('/search/results', { query: { q: trimmed, media_type: mediaType } })
      .then(payload => { if (!cancelled) setView({ state: payload.state || 'ready', props: payload }); })
      .catch(() => { if (!cancelled) setView({ state: 'error', props: {} }); });
    return () => { cancelled = true; };
  }, [session, query, mediaType, attempt]);

  const onLoadMore = useCallback(async row => {
    const payload = await session.request('/search/results', {
      query: searchRowParams(row, { query: String(query).trim(), mediaType }),
    });
    return payload.row ? mergeSearchRowPage(row, payload.row) : null;
  }, [session, query, mediaType]);

  const onLoadOnlineRow = useCallback(source => session.request('/search/results', {
    query: onlineRowParams(source, { query: String(query).trim(), mediaType }),
  }), [session, query, mediaType]);

  const openCard = useCallback(item => onOpenDetail?.(item?.card), [onOpenDetail]);

  return <SearchResults
    {...view.props}
    state={view.state}
    palette={palette}
    itemWidth={itemWidth}
    onOpenCard={openCard}
    onOpenLink={(_href, item) => openCard(item)}
    onAction={(_action, item) => openCard(item)}
    railComponent={WindowedRail}
    onLoadMore={onLoadMore}
    onLoadOnlineRow={onLoadOnlineRow}
    onRetry={() => setAttempt(current => current + 1)}
  />;
}
