import React, { useState } from 'react';
import { DetailHistoryDialog } from '../../../frontend/ui/DetailChildren';
import { Screen } from '../components/Screen';
import {
  AlbumPage,
  ArtistPage,
  DateEntryModal,
  MusicTabs,
  NotesModal,
  ShowPage,
  TrackPage,
  TrackingModal,
  listenDate,
} from '../components/MusicParts';
import {
  createMusicLibrary,
  findAlbum,
  findTrack,
  flattenAlbums,
} from '../data/musicDemo';
import { palette } from '../theme';

const surface = {
  id: 'MUSIC',
  status: 'in_progress',
  title: 'Music and podcasts',
  where: 'Artist, album, track and podcast detail',
  note: 'Artist relations, discography, album tracks, per-track notes, scores and play history, show/episode filtering, pagination, repeats and podcast tracking now use the shared React Native presentation with realistic demo data. The web artist, album, track and podcast pages remain server-owned and keep their permissions, feed and RSS refresh, tracking writes and progressive fallback, so the surface stays in progress until transport and the remaining web controls are mapped.',
};

const TABS = [
  { key: 'artist', label: 'Artist' },
  { key: 'album', label: 'Album' },
  { key: 'podcast', label: 'Podcast' },
];

const EMPTY_DIALOG = null;

function sortDescending(entries) {
  return [...entries].sort((left, right) => (
    `${right.date || ''} ${right.time || ''}`.localeCompare(`${left.date || ''} ${left.time || ''}`)
  ));
}

function trackHistoryRows(track) {
  return sortDescending(track.listens).map((entry, index) => ({
    key: entry.id,
    dateLabel: listenDate(entry),
    actionLabel: index === 0 ? 'Latest listen' : 'Repeat listen',
    note: track.score == null ? '' : `Score ${track.score}/10`,
  }));
}

function episodeHistoryRows(episode) {
  return sortDescending(episode.plays).map((entry, index) => ({
    key: entry.id,
    dateLabel: listenDate(entry),
    actionLabel: index === 0 ? 'Latest play' : 'Repeat play',
    note: entry.progress || (episode.score == null ? '' : `Score ${episode.score}/10`),
  }));
}

function albumHistoryRows(album) {
  const rows = album.tracks.flatMap(track => track.listens.map(entry => ({
    key: `${track.id}-${entry.id}`,
    date: entry.date,
    time: entry.time,
    dateLabel: listenDate(entry),
    actionLabel: track.title,
    note: `Track ${track.number}`,
  })));
  return sortDescending(rows);
}

function artistHistoryRows(albums) {
  return albums.flatMap(album => album.tracks.flatMap(track => track.listens.map(entry => ({
    key: `${track.id}-${entry.id}`,
    date: entry.date,
    time: entry.time,
    dateLabel: listenDate(entry),
    actionLabel: track.title,
    note: album.title,
  }))));
}

function showHistoryRows(episodes) {
  return episodes.flatMap(episode => episode.plays.map(entry => ({
    key: `${episode.id}-${entry.id}`,
    date: entry.date,
    time: entry.time,
    dateLabel: listenDate(entry),
    actionLabel: episode.title,
    note: `Episode ${episode.number}`,
  })));
}

export default function MusicScreen({ onBack }) {
  const [library, setLibrary] = useState(createMusicLibrary);
  const [tab, setTab] = useState('artist');
  const [selectedAlbumId, setSelectedAlbumId] = useState(() => flattenAlbums(createMusicLibrary().artist)[0].id);
  const [selectedTrackId, setSelectedTrackId] = useState(null);
  const [episodeFilter, setEpisodeFilter] = useState('all');
  const [visibleEpisodes, setVisibleEpisodes] = useState(4);
  const [dialog, setDialog] = useState(EMPTY_DIALOG);
  const [dateValue, setDateValue] = useState('2026-11-04');

  const artist = library.artist;
  const albums = flattenAlbums(artist);
  const album = findAlbum(library, selectedAlbumId) || albums[0];
  const selected = selectedTrackId ? findTrack(library, selectedTrackId) : null;
  const show = library.show;

  function changeTab(next) {
    setTab(next);
    setSelectedTrackId(null);
  }

  function openAlbum(next) {
    setSelectedAlbumId(next.id);
    setSelectedTrackId(null);
    setTab('album');
  }

  function updateArtist(updater) {
    setLibrary(current => ({ ...current, artist: updater(current.artist) }));
  }

  function updateAlbum(albumId, updater) {
    setLibrary(current => ({
      ...current,
      artist: {
        ...current.artist,
        discography: current.artist.discography.map(group => ({
          ...group,
          albums: (group.albums || []).map(item => (item.id === albumId ? updater(item) : item)),
        })),
      },
    }));
  }

  function updateTrack(trackId, updater) {
    setLibrary(current => ({
      ...current,
      artist: {
        ...current.artist,
        discography: current.artist.discography.map(group => ({
          ...group,
          albums: (group.albums || []).map(item => ({
            ...item,
            tracks: item.tracks.map(entry => (entry.id === trackId ? updater(entry) : entry)),
          })),
        })),
      },
    }));
  }

  function updateShow(updater) {
    setLibrary(current => ({ ...current, show: updater(current.show) }));
  }

  function updateEpisode(episodeId, updater) {
    setLibrary(current => ({
      ...current,
      show: {
        ...current.show,
        episodes: current.show.episodes.map(episode => (
          episode.id === episodeId ? updater(episode) : episode
        )),
      },
    }));
  }

  function openDateDialog(target, item) {
    setDateValue('2026-11-04');
    setDialog({ type: 'date', target, id: item.id, title: item.title, subtitle: target === 'track' ? album.title : `Episode ${item.number} · ${show.title}`, suggestionDate: target === 'episode' ? item.published : album.releaseDate });
  }

  function confirmDate() {
    if (!dialog) return;
    const [date, time = '12:00'] = dateValue.split('T');
    if (dialog.target === 'track') {
      updateTrack(dialog.id, track => ({
        ...track,
        listens: [{
          id: `listen-${Date.now()}`,
          date,
          time,
          repeat: track.listens.length > 0,
        }, ...track.listens],
      }));
    } else {
      updateEpisode(dialog.id, episode => ({
        ...episode,
        inProgress: false,
        plays: [{
          id: `play-${Date.now()}`,
          date,
          time,
          minutes: episode.minutes,
          repeat: episode.plays.length > 0,
        }, ...episode.plays],
      }));
    }
    setDialog(EMPTY_DIALOG);
  }

  function openNotes(target, item) {
    setDialog({ type: 'notes', target, id: item.id, title: item.title, subtitle: target === 'episode' ? `Episode ${item.number} · ${show.title}` : album.title, value: item.notes || '' });
  }

  function openHistory(target, item) {
    setDialog({ type: 'history', target, id: item.id, title: item.title });
  }

  function openTracking(target, item) {
    setDialog({ type: 'tracking', target, id: item.id, title: item.title });
  }

  function saveTracking(draft) {
    if (!dialog) return;
    if (dialog.target === 'artist') {
      updateArtist(current => ({ ...current, status: draft.status, score: draft.score, notes: draft.notes }));
    } else if (dialog.target === 'album') {
      updateAlbum(dialog.id, current => ({ ...current, status: draft.status, score: draft.score, notes: draft.notes }));
    } else {
      updateShow(current => ({ ...current, status: draft.status, score: draft.score, notes: draft.notes }));
    }
    setDialog(EMPTY_DIALOG);
  }

  function saveNotes(value) {
    if (!dialog) return;
    if (dialog.target === 'track') {
      updateTrack(dialog.id, track => ({ ...track, notes: value }));
    } else {
      updateEpisode(dialog.id, episode => ({ ...episode, notes: value }));
    }
    setDialog(EMPTY_DIALOG);
  }

  function rateArtist(score) {
    updateArtist(current => ({ ...current, score }));
  }

  function rateAlbum(score) {
    updateAlbum(album.id, current => ({ ...current, score }));
  }

  function rateTrack(track, score) {
    updateTrack(track.id, current => ({ ...current, score }));
  }

  function rateEpisode(episode, score) {
    updateEpisode(episode.id, current => ({ ...current, score }));
  }

  function handleTrackAction(key, targetAlbum, track) {
    if (key === 'listen') openDateDialog('track', track);
    else if (key === 'notes') openNotes('track', { ...track, title: track.title });
    else if (key === 'history') openHistory('track', track);
  }

  function handleEpisodeAction(key, episode) {
    if (key === 'play') openDateDialog('episode', episode);
    else if (key === 'notes') openNotes('episode', episode);
    else if (key === 'history') openHistory('episode', episode);
  }

  function deleteListen(trackId, listenId) {
    updateTrack(trackId, track => ({
      ...track,
      listens: track.listens.filter(entry => entry.id !== listenId),
    }));
  }

  function historyRows() {
    if (!dialog || dialog.type !== 'history') return [];
    if (dialog.target === 'track') {
      const found = findTrack(library, dialog.id);
      return found ? trackHistoryRows(found.track) : [];
    }
    if (dialog.target === 'episode') {
      const episode = show.episodes.find(item => item.id === dialog.id);
      return episode ? episodeHistoryRows(episode) : [];
    }
    if (dialog.target === 'album') {
      const target = findAlbum(library, dialog.id);
      return target ? albumHistoryRows(target) : [];
    }
    if (dialog.target === 'show') return sortDescending(showHistoryRows(show.episodes));
    return sortDescending(artistHistoryRows(albums));
  }

  const tracking = dialog?.type === 'tracking' ? {
    artist: { status: artist.status, score: artist.score, notes: artist.notes || '' },
    album: { status: album.status, score: album.score, notes: album.notes || '' },
    show: { status: show.status, score: show.score, notes: show.notes || '' },
  }[dialog.target] : null;

  return <Screen title="Music" subtitle="Artist, album and podcast detail" onBack={onBack}>
    <MusicTabs tabs={TABS} active={tab} onChange={changeTab} />

    {tab === 'artist'
      ? <ArtistPage artist={artist} albums={albums}
        onOpenAlbum={openAlbum}
        onTrack={() => openTracking('artist', artist)}
        onHistory={() => openHistory('artist', artist)}
        onRate={rateArtist} />
      : null}

    {tab === 'album' && !selected
      ? <AlbumPage album={album}
        onBack={() => setTab('artist')}
        onOpenTrack={track => setSelectedTrackId(track.id)}
        onTrack={() => openTracking('album', album)}
        onHistory={() => openHistory('album', album)}
        onRate={rateAlbum}
        onAction={(key, targetAlbum, track) => handleTrackAction(key, targetAlbum, track)}
        onTrackRate={rateTrack} />
      : null}

    {tab === 'album' && selected
      ? <TrackPage key={selected.track.id} album={selected.album} track={selected.track}
        onBack={() => setSelectedTrackId(null)}
        onRate={score => rateTrack(selected.track, score)}
        onAddListen={() => openDateDialog('track', selected.track)}
        onOpenNotes={() => openNotes('track', selected.track)}
        onSaveNotes={value => updateTrack(selected.track.id, track => ({ ...track, notes: value }))}
        onDeleteListen={listenId => deleteListen(selected.track.id, listenId)}
        onOpenHistory={() => openHistory('track', selected.track)} />
      : null}

    {tab === 'podcast'
      ? <ShowPage show={show} episodes={show.episodes}
        episodeFilter={episodeFilter}
        onFilter={value => { setEpisodeFilter(value); setVisibleEpisodes(4); }}
        visibleCount={visibleEpisodes}
        onLoadMore={() => setVisibleEpisodes(current => current + 4)}
        onTrack={() => openTracking('show', show)}
        onHistory={() => openHistory('show', show)}
        onRate={score => updateShow(current => ({ ...current, score }))}
        onAction={handleEpisodeAction}
        onEpisodeRate={rateEpisode} />
      : null}

    <DateEntryModal open={dialog?.type === 'date'}
      title={dialog?.target === 'track' ? 'Add listen' : 'Add play'}
      subtitle={dialog?.subtitle}
      value={dateValue}
      onChange={setDateValue}
      onClose={() => setDialog(EMPTY_DIALOG)}
      onConfirm={confirmDate}
      confirmLabel={dialog?.target === 'track' ? 'Add listen' : 'Add play'}
      suggestionDate={dialog?.suggestionDate || ''} />

    <TrackingModal open={dialog?.type === 'tracking'}
      title={dialog?.title || 'Tracking'}
      subtitle={dialog?.target === 'show' ? 'Podcast show' : dialog?.target === 'album' ? 'Album' : 'Artist'}
      status={tracking?.status || null}
      score={tracking?.score ?? null}
      notes={tracking?.notes || ''}
      onClose={() => setDialog(EMPTY_DIALOG)}
      onSave={saveTracking} />

    <NotesModal open={dialog?.type === 'notes'}
      title={dialog?.title || 'Notes'}
      subtitle={dialog?.subtitle}
      value={dialog?.value || ''}
      onClose={() => setDialog(EMPTY_DIALOG)}
      onSave={saveNotes} />

    <DetailHistoryDialog open={dialog?.type === 'history'}
      title={dialog ? dialog.title : 'Activity history'}
      rows={historyRows()}
      labels={{ history: 'Activity history', close: 'Close', noHistory: 'No activity recorded yet.' }}
      palette={palette}
      onClose={() => setDialog(EMPTY_DIALOG)} />
  </Screen>;
}
