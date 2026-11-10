import React, { useEffect, useMemo, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { SearchResults } from '../../../frontend/ui/SearchResults.jsx';
import { palette, mediaCardPalette, radius } from '../theme';
import { createSearchTransport } from '../data/searchTransport';
import { enrichServerCard, musicCreateFromHref, routeCardHref } from '../data/serverCardCore';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import MediaCardSlot from './MediaCardSlot';

export const surface = {
  id: 'SEARCH-RESULTS',
  status: 'in_progress',
  title: 'Search result sections, paging and source scope',
  where: 'Search results',
  note: 'The shared SearchResults view renders the server search presentation from /api/v1/search/results/ (library groups for All, library plus online sections for a media type, music artist and album subsections, podcast tips, source pills per type, paging, empty and error copy). Every result card renders through the shared media card host, so Track, Lists and rating write in place; online music artists and albums create their entry through /api/v1/search/music/create/ and open it. A podcast RSS or Apple Podcasts link pasted into the query is searched by the server. Signed-out and failed requests show their own state with retry. Browser, iOS and Android runtime passes were not run.',
};

const searchPalette = () => ({
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  accent: palette.accent,
  accentText: palette.accentContrast,
  link: palette.link,
  danger: palette.danger,
  radius: radius.sm,
  ...mediaCardPalette,
});

export default function SearchResultsSlot({
  query = '',
  mediaType = 'all',
  navigate,
  onSelectMediaType,
}) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => createSearchTransport(session ? { auth: session } : {}),
    [session],
  );
  const [source, setSource] = useState('');
  const [layout, setLayout] = useState('grid');
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({ state: 'idle', props: null, error: '' });
  const [creating, setCreating] = useState('');
  const { width: windowWidth } = useWindowDimensions();

  // A new query or media type starts from the server's default source, page one.
  useEffect(() => { setSource(''); setPage(1); }, [query, mediaType]);

  useEffect(() => {
    if (!query.trim()) {
      setResult({ state: 'idle', props: null, error: '' });
      return undefined;
    }
    let active = true;
    setResult(current => ({ ...current, state: 'loading', error: '' }));
    transport.loadResults({ query, mediaType, source, page, layout }).then(props => {
      if (active) setResult({ state: props.state || 'ready', props, error: '' });
    }).catch(cause => {
      if (active) {
        setResult({
          state: 'error',
          props: null,
          error: cause?.message || 'Search could not load. Please try again.',
        });
      }
    });
    return () => { active = false; };
  }, [transport, query, mediaType, source, page, layout, attempt]);

  if (result.state === 'idle') return null;

  const props = result.props || {};
  const errorBody = result.error || props.errors?.[0];
  const signedOut = transport.mode !== 'server';
  const labels = {
    ...(props.labels || {}),
    ...(errorBody ? { errorBody } : {}),
    ...(signedOut ? { errorTitle: 'Sign in required' } : {}),
  };

  async function openCard(card) {
    // Online music artists and albums are created from the provider id first.
    const create = musicCreateFromHref(card?.href);
    if (create) {
      setCreating(card.title || '');
      try {
        const made = await transport.createMusic(create);
        navigate?.('Music', {
          artistId: made.artist_id,
          ...(made.album_id ? { albumId: made.album_id } : {}),
        });
      } catch (cause) {
        setResult(current => ({ ...current, error: cause?.message || 'Could not add this entry.' }));
      } finally {
        setCreating('');
      }
      return;
    }
    if (!routeCardHref(card?.href, navigate)) navigate?.('Detail', { item: card });
  }

  const renderCard = item => <MediaCardSlot
    items={[{ key: item.cardKey || `${item.title}-${item.href}`, model: item.layout === 'row' || layout === 'list' ? { ...enrichServerCard(item), rowSplit: true, rowWidth: windowWidth - 32 } : enrichServerCard(item) }]}
    onOpenDetail={() => openCard(item)}
    onOpenLink={href => { if (!routeCardHref(href, navigate)) openCard(item); }} />;

  return <SearchResults
    title={props.title}
    state={creating ? 'loading' : result.state === 'idle' ? 'ready' : result.state}
    labels={labels}
    palette={searchPalette()}
    scope={props.scope}
    layoutOptions={props.layoutOptions}
    notes={props.notes || []}
    sections={props.sections || []}
    paging={props.paging}
    empty={props.empty}
    renderCard={renderCard}
    iconToggle
    onSelectScope={option => { setPage(1); setSource(option.value); }}
    onSelectLayout={option => setLayout(option.value)}
    onSearchOnline={option => {
      const match = String(option?.href || '').match(/[?&]media_type=([^&]+)/);
      if (match) onSelectMediaType?.(decodeURIComponent(match[1]));
    }}
    onPage={target => setPage(target.number
      ? target.number
      : (target === props.paging?.previous ? Math.max(1, page - 1) : page + 1))}
    onRetry={signedOut ? undefined : () => setAttempt(current => current + 1)}
  />;
}
