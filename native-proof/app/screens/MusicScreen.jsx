import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { DetailHistoryDialog } from '../../../frontend/ui/DetailChildren';
import { MarkdownPreview } from '../../../frontend/ui/MarkdownPreview.native';
import { Screen } from '../components/Screen';
import {
  AlbumPage,
  ArtistPage,
  DateEntryModal,
  MusicView,
  NotesModal,
  SectionHeading,
  SheetModal,
  ShowPage,
  TrackPage,
  TrackingModal,
  listenDate,
} from '../../../frontend/pages/MusicView';
import {
  createMusicLibrary,
  findAlbum,
  findTrack,
  flattenAlbums,
} from '../data/musicDemo';
import { createMusicTransport } from '../data/musicTransport';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'MUSIC',
  status: 'in_progress',
  title: 'Music and podcasts',
  where: 'Artist, album, track and podcast detail',
  note: 'The native transport uses the authenticated session and maps note writes, history deletion, tracker removal, artist membership and discography sync, album metadata sync, mark-all-played, delete-all-plays and the tracking and play endpoints. Artist relations, discography, album tracks, per-track notes, scores and play history, show/episode filtering, pagination, repeats and podcast tracking use the shared React Native presentation, with library actions, confirmations and empty states for every tab. The surface stays in progress because server-mode hydration still renders the seeded demo records (loadArtist, loadAlbum, loadShow, loadEpisodes and loadAlbumTracks payloads are unmapped), tags, links, list membership and artwork changes have no native contract or control, podcast feed/RSS refresh stays server-owned, episode scores have no transport method, and iOS/Android runtime passes are outstanding.',
};

const TABS = [
  { key: 'artist', label: 'Artist' },
  { key: 'album', label: 'Album' },
  { key: 'podcast', label: 'Podcast' },
];

const EMPTY_DIALOG = null;
const TODAY = '2026-11-04';

function countLabel(count, singular, plural) {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

function EmptyPanel({ title, copy, actionLabel, onAction }) {
  return <View style={styles.empty}>
    <Text style={styles.emptyTitle}>{title}</Text>
    {copy ? <Text style={styles.emptyCopy}>{copy}</Text> : null}
    {actionLabel ? <Button label={actionLabel} tone="surface" onPress={onAction} /> : null}
  </View>;
}

function remoteId(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function sortDescending(entries) {
  return [...entries].sort((left, right) => (
    `${right.date || ''} ${right.time || ''}`.localeCompare(`${left.date || ''} ${left.time || ''}`)
  ));
}

function relationModel(relation) {
  const tracker = relation.tracker || {};
  return {
    id: relation.id,
    name: relation.name,
    role: relation.role || '',
    current: Boolean(relation.current),
    image: relation.image || '',
    status: tracker.status || null,
    score: tracker.score == null ? null : Number(tracker.score),
  };
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

function totalListens(albums) {
  return albums.reduce((count, album) => (
    count + album.tracks.reduce((sum, track) => sum + track.listens.length, 0)
  ), 0);
}

export default function MusicScreen({ onBack, transport: injectedTransport }) {
  const [transport] = useState(() => injectedTransport || createMusicTransport());
  const [transportError, setTransportError] = useState('');
  const [library, setLibrary] = useState(createMusicLibrary);
  const [tab, setTab] = useState('artist');
  const [selectedAlbumId, setSelectedAlbumId] = useState(() => (
    flattenAlbums(createMusicLibrary().artist)[0]?.id ?? null
  ));
  const [selectedTrackId, setSelectedTrackId] = useState(null);
  const [episodeFilter, setEpisodeFilter] = useState('all');
  const [visibleEpisodes, setVisibleEpisodes] = useState(4);
  const [dialog, setDialog] = useState(EMPTY_DIALOG);
  const [confirm, setConfirm] = useState(null);
  const [notice, setNotice] = useState('');
  const [dateValue, setDateValue] = useState(TODAY);

  useEffect(() => {
    const artistId = remoteId(library.artist.artistId ?? library.artist.id);
    if (!artistId || transport.mode !== 'server') return;
    let active = true;
    transport.loadArtistRelations({ artistId }).then(payload => {
      if (!active || !payload) return;
      setLibrary(current => ({
        ...current,
        artist: {
          ...current.artist,
          relations: {
            members: (payload.members || []).map(relationModel),
            alsoIn: (payload.also_in || []).map(relationModel),
          },
        },
      }));
    }).catch(error => {
      if (active) setTransportError(error?.message || 'Could not load artist relations.');
    });
    return () => { active = false; };
  }, [library.artist.artistId, library.artist.id, transport]);

  const artist = library.artist;
  const albums = flattenAlbums(artist);

  function persist(action, payload) {
    if (transport.mode !== 'server') return Promise.resolve(null);
    setTransportError('');
    return Promise.resolve(transport[action](payload)).catch(error => {
      setTransportError(error?.message || 'The server rejected the music change.');
      return null;
    });
  }
  const album = findAlbum(library, selectedAlbumId) || albums[0];
  const selected = selectedTrackId ? findTrack(library, selectedTrackId) : null;
  const show = library.show;
  const artistRemoteId = remoteId(artist.artistId ?? artist.id);
  const albumRemoteId = remoteId(album?.albumId ?? album?.id);
  const showRemoteId = remoteId(show.showId ?? show.id);

  function changeTab(next) {
    setTab(next);
    setSelectedTrackId(null);
    setNotice('');
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

  function askConfirm(config) {
    setConfirm(config);
  }

  function runConfirm() {
    const action = confirm?.onConfirm;
    setConfirm(null);
    if (action) action();
  }

  function withoutListens(target) {
    return {
      ...target,
      plays: 0,
      tracks: target.tracks.map(track => ({ ...track, listens: [] })),
    };
  }

  function confirmDeleteArtistPlays() {
    const total = artist.totalPlays || totalListens(albums);
    askConfirm({
      title: 'Delete all plays?',
      message: total
        ? `This removes ${countLabel(total, 'listen', 'listens')} across ${countLabel(albums.length, 'release', 'releases')} and cannot be undone.`
        : 'No plays are recorded for this artist.',
      confirmLabel: 'Delete plays',
      onConfirm() {
        updateArtist(current => ({
          ...current,
          totalPlays: 0,
          discography: current.discography.map(group => ({
            ...group,
            albums: (group.albums || []).map(withoutListens),
          })),
        }));
        setNotice(total
          ? `Deleted ${countLabel(total, 'listen', 'listens')}.`
          : 'No plays to delete.');
        if (artistRemoteId) persist('deleteArtistPlays', { artistId: artistRemoteId });
      },
    });
  }

  function confirmDeleteAlbumPlays() {
    if (!album) return;
    const total = album.plays || album.tracks.reduce((sum, track) => sum + track.listens.length, 0);
    askConfirm({
      title: 'Delete all plays?',
      message: total
        ? `This removes ${countLabel(total, 'listen', 'listens')} from ${album.title} and cannot be undone.`
        : `No plays are recorded for ${album.title}.`,
      confirmLabel: 'Delete plays',
      onConfirm() {
        updateAlbum(album.id, withoutListens);
        updateArtist(current => ({
          ...current,
          totalPlays: Math.max(0, (current.totalPlays || 0) - (album.plays || 0)),
        }));
        setNotice(total
          ? `Deleted ${countLabel(total, 'listen', 'listens')}.`
          : 'No plays to delete.');
        if (albumRemoteId) persist('deleteAlbumPlays', { albumId: albumRemoteId });
      },
    });
  }

  function confirmRemoveArtist() {
    askConfirm({
      title: 'Remove artist from library?',
      message: 'The artist tracker is removed. Listening history stays in your account.',
      confirmLabel: 'Remove artist',
      onConfirm() {
        updateArtist(current => ({ ...current, status: null, score: null }));
        setNotice('Artist removed from your library.');
        if (artistRemoteId) persist('removeArtist', { artistId: artistRemoteId });
      },
    });
  }

  function confirmRemoveAlbum() {
    if (!album) return;
    askConfirm({
      title: 'Remove album from library?',
      message: `The ${album.title} tracker is removed. Listening history stays in your account.`,
      confirmLabel: 'Remove album',
      onConfirm() {
        updateAlbum(album.id, current => ({ ...current, status: null, score: null }));
        setNotice('Album removed from your library.');
        if (albumRemoteId) persist('removeAlbum', { albumId: albumRemoteId });
      },
    });
  }

  function confirmRemoveShow() {
    askConfirm({
      title: 'Remove podcast from library?',
      message: 'The show tracker is removed. Episode plays stay in your account.',
      confirmLabel: 'Remove podcast',
      onConfirm() {
        updateShow(current => ({ ...current, status: null, score: null }));
        setNotice('Podcast removed from your library.');
        if (showRemoteId) persist('removeShow', { showId: showRemoteId });
      },
    });
  }

  function confirmMarkAllPlayed() {
    const remaining = show.episodes.filter(episode => episode.inProgress || !episode.plays.length);
    askConfirm({
      title: 'Mark all episodes played?',
      message: remaining.length
        ? `${countLabel(remaining.length, 'episode', 'episodes')} will be recorded as played today.`
        : 'Every episode is already played.',
      confirmLabel: 'Mark all played',
      onConfirm() {
        updateShow(current => ({
          ...current,
          episodes: current.episodes.map(episode => {
            if (!episode.inProgress && episode.plays.length) return episode;
            return {
              ...episode,
              inProgress: false,
              plays: [{
                id: `play-${episode.id}-${Date.now()}`,
                date: TODAY,
                time: '12:00',
                minutes: episode.minutes,
                repeat: episode.plays.length > 0,
              }, ...episode.plays],
            };
          }),
        }));
        setNotice(remaining.length
          ? `Marked ${countLabel(remaining.length, 'episode', 'episodes')} played.`
          : 'Every episode was already played.');
        if (showRemoteId) persist('markAllPlayed', { showId: showRemoteId });
      },
    });
  }

  async function syncArtistDiscography() {
    if (!artistRemoteId) {
      setNotice('Discography sync needs a signed-in server. The demo discography is already current.');
      return;
    }
    const result = await persist('syncArtistDiscography', { artistId: artistRemoteId });
    if (result) {
      setNotice(`Synced ${countLabel(Number(result.synced_albums) || 0, 'release', 'releases')} from MusicBrainz.`);
    }
  }

  async function syncArtistMembers() {
    const result = await persist('syncArtistMembers', { artistId: artistRemoteId });
    if (result) {
      setNotice(`Synced ${countLabel(Number(result.synced_members) || 0, 'member', 'members')} from MusicBrainz.`);
    }
  }

  async function syncAlbumMetadata() {
    const result = await persist('syncAlbumMetadata', { albumId: albumRemoteId });
    if (result) {
      setNotice(`Synced ${countLabel(Number(result.synced_tracks) || 0, 'track', 'tracks')} from MusicBrainz.`);
    }
  }

  function openDateDialog(target, item) {
    setDateValue(TODAY);
    const albumName = album ? album.title : artist.name;
    setDialog({
      type: 'date',
      target,
      id: item.id,
      title: item.title,
      subtitle: target === 'track'
        ? (item.duration ? `${albumName} · ${item.duration}` : albumName)
        : `Episode ${item.number} · ${show.title}`,
      suggestionDate: target === 'episode' ? item.published : album?.releaseDate,
    });
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
      const found = findTrack(library, dialog.id);
      const albumId = remoteId(found?.album?.albumId ?? found?.album?.id);
      const trackId = remoteId(found?.track?.trackId ?? found?.track?.id);
      if (found?.album) {
        updateAlbum(found.album.id, current => ({ ...current, plays: (current.plays || 0) + 1 }));
        updateArtist(current => ({ ...current, totalPlays: (current.totalPlays || 0) + 1 }));
      }
      if (albumId) persist('addListen', { albumId, trackId, endDate: `${date}T${time}:00` });
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
      const showId = remoteId(show.showId ?? show.id);
      const episodeId = remoteId(dialog.id);
      if (showId) persist('addEpisodePlay', { showId, episodeId, endDate: `${date}T${time}:00` });
    }
    setDialog(EMPTY_DIALOG);
  }

  function openNotes(target, item) {
    setDialog({
      type: 'notes',
      target,
      id: item.id,
      title: item.title,
      subtitle: target === 'episode'
        ? `Episode ${item.number} · ${show.title}`
        : (album ? album.title : artist.name),
      value: item.notes || '',
    });
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
      const artistId = remoteId(artist.artistId ?? artist.id);
      if (artistId) persist('saveArtist', { artistId, ...draft });
    } else if (dialog.target === 'album' && album) {
      updateAlbum(dialog.id, current => ({ ...current, status: draft.status, score: draft.score, notes: draft.notes }));
      const albumId = remoteId(album.albumId ?? album.id);
      if (albumId) persist('saveAlbum', { albumId, ...draft });
    } else {
      updateShow(current => ({ ...current, status: draft.status, score: draft.score, notes: draft.notes }));
      const showId = remoteId(show.showId ?? show.id);
      if (showId) persist('saveShow', { showId, ...draft });
    }
    setDialog(EMPTY_DIALOG);
  }

  function saveTrackNotes(trackId, value) {
    updateTrack(trackId, track => ({ ...track, notes: value }));
    const remoteTrackId = remoteId(trackId);
    if (remoteTrackId) persist('saveTrackNotes', { trackId: remoteTrackId, notes: value });
  }

  function saveNotes(value) {
    if (!dialog) return;
    if (dialog.target === 'track') {
      saveTrackNotes(dialog.id, value);
    } else {
      updateEpisode(dialog.id, episode => ({ ...episode, notes: value }));
      const episodeId = remoteId(dialog.id);
      if (episodeId) persist('saveEpisodeNotes', { episodeId, notes: value });
    }
    setDialog(EMPTY_DIALOG);
  }

  function rateArtist(score) {
    updateArtist(current => ({ ...current, score }));
    if (artistRemoteId && artist.status) persist('saveArtist', { artistId: artistRemoteId, score });
  }

  function rateAlbum(score) {
    if (!album) return;
    updateAlbum(album.id, current => ({ ...current, score }));
    if (albumRemoteId && album.status) persist('saveAlbum', { albumId: albumRemoteId, score });
  }

  function rateTrack(track, score) {
    updateTrack(track.id, current => ({ ...current, score }));
    const musicId = remoteId(track.musicId);
    if (musicId) persist('rateTrack', { musicId, score });
  }

  function rateShow(score) {
    updateShow(current => ({ ...current, score }));
    if (showRemoteId && show.status) persist('saveShow', { showId: showRemoteId, score });
  }

  // Episode scores have no native transport method yet; the shared episode row
  // still updates its local score so the demo keeps the same interaction.
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

  function deleteListen(trackId, entry) {
    updateTrack(trackId, track => ({
      ...track,
      listens: track.listens.filter(item => item.id !== entry.id),
    }));
    const found = findTrack(library, trackId);
    if (found?.album) {
      updateAlbum(found.album.id, current => ({
        ...current,
        plays: Math.max(0, (current.plays || 0) - 1),
      }));
      updateArtist(current => ({
        ...current,
        totalPlays: Math.max(0, (current.totalPlays || 0) - 1),
      }));
    }
    const historyId = remoteId(entry.historyId ?? entry.id);
    if (historyId) persist('deleteHistory', { mediaType: 'music', historyId });
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
    album: { status: album?.status, score: album?.score, notes: album?.notes || '' },
    show: { status: show.status, score: show.score, notes: show.notes || '' },
  }[dialog.target] : null;

  return <Screen onBack={onBack}>
    <MusicView tabs={TABS} active={tab} onChange={changeTab}
      palette={palette} error={transportError} notice={notice}>

    {tab === 'artist'
      ? <>
        <ArtistPage artist={artist} albums={albums}
          onOpenAlbum={openAlbum}
          onTrack={() => openTracking('artist', artist)}
          onHistory={() => openHistory('artist', artist)}
          onRate={rateArtist}
          onSyncMembers={artistRemoteId ? syncArtistMembers : null} />
        {artist.relations.members.length || artist.relations.alsoIn.length
          ? null
          : <EmptyPanel title="No band relations yet"
            copy="Sync members from MusicBrainz to show current and former collaborators."
            actionLabel={artistRemoteId ? 'Sync members' : null}
            onAction={artistRemoteId ? syncArtistMembers : undefined} />}
        {albums.length
          ? null
          : <EmptyPanel title="No releases collected yet"
            copy="Sync the discography to pull albums and EPs from MusicBrainz."
            actionLabel="Sync discography"
            onAction={syncArtistDiscography} />}
        <View style={styles.section}>
          <SectionHeading title="Artist actions"
            copy="Sync from MusicBrainz, delete this artist's plays or remove the tracker. Removing a tracker keeps your listening history." />
          <View style={styles.actionRow}>
            <Button label="Sync discography" tone="surface" onPress={syncArtistDiscography} />
            <Button label="Delete all plays" tone="ghost-danger" onPress={confirmDeleteArtistPlays} />
            {artist.status ? <Button label="Remove from library" tone="ghost-danger" onPress={confirmRemoveArtist} /> : null}
          </View>
        </View>
      </>
      : null}

    {tab === 'album' && !selected
      ? (album
        ? <>
          <AlbumPage album={album}
            onBack={() => setTab('artist')}
            onOpenTrack={track => setSelectedTrackId(track.id)}
            onTrack={() => openTracking('album', album)}
            onHistory={() => openHistory('album', album)}
            onRate={rateAlbum}
            onAction={(key, targetAlbum, track) => handleTrackAction(key, targetAlbum, track)}
            onTrackRate={rateTrack}
            onSyncMetadata={albumRemoteId ? syncAlbumMetadata : null} />
          {album.tracks.length
            ? null
            : <EmptyPanel title="No tracks yet"
              copy="Sync the album metadata to rebuild the tracklist from MusicBrainz."
              actionLabel={albumRemoteId ? 'Sync metadata' : null}
              onAction={albumRemoteId ? syncAlbumMetadata : undefined} />}
          <View style={styles.section}>
            <SectionHeading title="Album actions"
              copy="Delete this album's plays or remove its tracker. Sync metadata stays with the album summary above." />
            <View style={styles.actionRow}>
              <Button label="Delete all plays" tone="ghost-danger" onPress={confirmDeleteAlbumPlays} />
              {album.status ? <Button label="Remove album" tone="ghost-danger" onPress={confirmRemoveAlbum} /> : null}
            </View>
          </View>
        </>
        : <EmptyPanel title="No release selected"
          copy="Open a release from the artist discography to see its tracks."
          actionLabel="Back to artist"
          onAction={() => setTab('artist')} />)
      : null}

    {tab === 'album' && selected
      ? <TrackPage key={selected.track.id} album={selected.album} track={selected.track}
        onBack={() => setSelectedTrackId(null)}
        onRate={score => rateTrack(selected.track, score)}
        onAddListen={() => openDateDialog('track', selected.track)}
        onOpenNotes={() => openNotes('track', selected.track)}
        onSaveNotes={value => saveTrackNotes(selected.track.id, value)}
        onDeleteListen={entry => deleteListen(selected.track.id, entry)}
        onOpenHistory={() => openHistory('track', selected.track)} Preview={MarkdownPreview} />
      : null}

    {tab === 'podcast'
      ? <>
        <ShowPage show={show} episodes={show.episodes}
          episodeFilter={episodeFilter}
          onFilter={value => { setEpisodeFilter(value); setVisibleEpisodes(4); setNotice(''); }}
          visibleCount={visibleEpisodes}
          onLoadMore={() => setVisibleEpisodes(current => current + 4)}
          onTrack={() => openTracking('show', show)}
          onHistory={() => openHistory('show', show)}
          onRate={rateShow}
          onAction={handleEpisodeAction}
          onEpisodeRate={rateEpisode} />
        <View style={styles.section}>
          <SectionHeading title="Show actions"
            copy="Record every unplayed episode in one step or remove the show tracker. Episode plays stay in your history." />
          <View style={styles.actionRow}>
            <Button label="Mark all played" tone="surface" onPress={confirmMarkAllPlayed} />
            {show.status ? <Button label="Remove podcast" tone="ghost-danger" onPress={confirmRemoveShow} /> : null}
          </View>
        </View>
      </>
      : null}
    </MusicView>

    <SheetModal open={Boolean(confirm)}
      title={confirm?.title || 'Confirm'}
      subtitle={confirm?.message}
      onClose={() => setConfirm(null)}>
      <View style={styles.modalActions}>
        <Button label="Cancel" tone="surface" onPress={() => setConfirm(null)} />
        <Button label={confirm?.confirmLabel || 'Confirm'} tone="danger-solid" onPress={runConfirm} />
      </View>
    </SheetModal>

    <DateEntryModal open={dialog?.type === 'date'}
      title={dialog?.target === 'track' ? 'Add listen' : 'Add play'}
      subtitle={dialog?.subtitle}
      value={dateValue}
      onChange={setDateValue}
      onClose={() => setDialog(EMPTY_DIALOG)}
      onConfirm={confirmDate}
      confirmLabel={dialog?.target === 'track' ? 'Add listen' : 'Add play'}
      suggestionDate={dialog?.suggestionDate || ''} />

    <TrackingModal open={dialog?.type === 'tracking'} Preview={MarkdownPreview}
      title={dialog?.title || 'Tracking'}
      subtitle={dialog?.target === 'show' ? 'Podcast show' : dialog?.target === 'album' ? 'Album' : 'Artist'}
      status={tracking?.status || null}
      score={tracking?.score ?? null}
      notes={tracking?.notes || ''}
      onClose={() => setDialog(EMPTY_DIALOG)}
      onSave={saveTracking} />

    <NotesModal open={dialog?.type === 'notes'} Preview={MarkdownPreview}
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

const styles = StyleSheet.create({
  notice: {
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.4)',
    borderRadius: 8,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  noticeText: { color: palette.danger, fontSize: 13 },
  successNotice: {
    borderWidth: 1,
    borderColor: 'rgba(16, 185, 129, 0.4)',
    borderRadius: 8,
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  successText: { color: palette.success, fontSize: 13 },
  section: { gap: spacing.md },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  empty: {
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: radius.md,
    backgroundColor: palette.surface,
    padding: spacing.lg,
    alignItems: 'center',
    gap: spacing.sm,
  },
  emptyTitle: { color: palette.text, fontSize: 14, fontWeight: '600', textAlign: 'center' },
  emptyCopy: { color: palette.textMuted, fontSize: 12, lineHeight: 18, textAlign: 'center' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', flexWrap: 'wrap', gap: spacing.sm },
});
