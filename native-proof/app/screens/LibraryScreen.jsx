import React from 'react';
import { LibraryPageView } from '../../../frontend/pages/LibraryPageView';
import { Screen } from '../components/Screen';
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
};

export default function LibraryScreen({ params, navigate }) {
  const mediaType = params?.mediaType;
  const title = MEDIA_TYPE_LABELS[mediaType] || 'Library';
  return <Screen chrome={false}>
    <LibraryPageView
      title={title}
      subtitle="Everything you track, filtered the way you left it"
      labels={{ loading: 'Loading your library…' }}
      palette={palette}
      search={<SearchSlot
        onOpenSearch={next => navigate('Search', next)}
        onOpenSuggestion={item => navigate('Detail', { item })}
      />}
      filters={<FiltersSlot />}
      selection={<BulkSlot onOpenDetail={() => navigate('Detail')} />}
      content={<TableSlot onOpenDetail={() => navigate('Detail')} />}
      footer={<ButtonSlot />}
    />
  </Screen>;
}
