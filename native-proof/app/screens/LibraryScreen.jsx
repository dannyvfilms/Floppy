import React, { useEffect, useState } from 'react';
import { LibraryPageView } from '../../../frontend/pages/LibraryPageView';
import { Screen } from '../components/Screen';
import { createLibraryTransport, mediaRowsFromPayload } from '../data/libraryTransport';
import { palette } from '../theme';
import BulkSlot from '../surfaces/BulkSlot';
import ButtonSlot from '../surfaces/ButtonSlot';
import FiltersSlot from '../surfaces/FiltersSlot';
import SearchSlot from '../surfaces/SearchSlot';
import TableSlot from '../surfaces/TableSlot';

const MEDIA_TYPE_LABELS = {
  movie: 'Movies',
  tv: 'Shows',
  anime: 'Anime',
  book: 'Books',
  comic: 'Comics',
  manga: 'Manga',
  game: 'Games',
  boardgame: 'Board Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

const PAGE_LIMIT = 30;

const labels = {
  loading: 'Loading your library…',
  retry: 'Try again',
  emptyTitle: 'Nothing here yet',
  emptyAction: 'Browse Discover',
};

export default function LibraryScreen({ params, navigate }) {
  const mediaType = params?.mediaType;
  const title = MEDIA_TYPE_LABELS[mediaType] || 'Library';
  const [transport] = useState(() => createLibraryTransport());
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [error, setError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (transport.mode !== 'server') {
      setLoading(false);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError('');
    transport.load({ mediaType, limit: PAGE_LIMIT, offset: 0 })
      .then(payload => {
        if (!active) return;
        setRows(mediaRowsFromPayload(payload));
        const value = Number(payload?.pagination?.total);
        setTotal(Number.isFinite(value) ? value : null);
        setLoading(false);
      })
      .catch(cause => {
        if (!active) return;
        setRows([]);
        setTotal(null);
        setError(cause?.message || 'Your library could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, mediaType, reloadToken]);

  const state = loading
    ? 'loading'
    : error
      ? 'error'
      : rows.length
        ? 'ready'
        : 'empty';

  return <Screen chrome={false}>
    <LibraryPageView
      title={title}
      subtitle="Everything you track, filtered the way you left it"
      count={total ?? (state === 'ready' ? rows.length : undefined)}
      countLabel={total === 1 ? 'item' : 'items'}
      labels={labels}
      palette={palette}
      state={state}
      error={error ? { title: 'Library could not load', body: error } : undefined}
      empty={transport.mode === 'local'
        ? { title: 'Sign in to see your library', body: 'Connect your Floppy server to load tracked media.' }
        : { title: 'Nothing here yet', body: 'Track something and it will appear in this library.' }}
      onRetry={() => setReloadToken(current => current + 1)}
      onEmptyAction={() => navigate('Discover')}
      search={<SearchSlot
        onOpenSearch={next => navigate('Search', next)}
        onOpenSuggestion={item => navigate('Detail', { item })}
      />}
      filters={<FiltersSlot />}
      selection={<BulkSlot onOpenDetail={() => navigate('Detail')} />}
      content={<TableSlot
        rows={rows}
        onOpenDetail={row => navigate('Detail', { item: row })}
        onTrackSave={(row, values) => transport.update({ identity: row.identity, values })}
        onTrackDelete={row => transport.remove({ identity: row.identity })} />}
      footer={<ButtonSlot />}
    />
  </Screen>;
}