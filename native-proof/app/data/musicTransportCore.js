const api = path => `/api/v1${path}`;
const artistPath = artistId => api(`/music/artists/${encodeURIComponent(artistId)}/`);
const albumPath = albumId => api(`/music/albums/${encodeURIComponent(albumId)}/`);
const showPath = showId => api(`/podcasts/shows/${encodeURIComponent(showId)}/`);

function trackerFields({ status, score, startDate, endDate, notes }) {
  const payload = {};
  if (status !== undefined) payload.status = status;
  if (score !== undefined) payload.score = score;
  if (startDate !== undefined) payload.start_date = startDate;
  if (endDate !== undefined) payload.end_date = endDate;
  if (notes !== undefined) payload.notes = notes;
  return payload;
}

// The native feature boundary maps the fork's music and podcast REST
// endpoints. Presentation receives plain values; credentials, CSRF, base URL
// and error handling stay in the request adapter behind this contract.
export function createRemoteMusicActions(request) {
  return {
    mode: 'server',
    loadArtist({ artistId }) {
      return request(artistPath(artistId));
    },
    saveArtist({ artistId, ...fields }) {
      return request(artistPath(artistId), {
        method: 'PATCH',
        json: trackerFields(fields),
      });
    },
    removeArtist({ artistId }) {
      return request(artistPath(artistId), { method: 'DELETE' });
    },
    syncArtistDiscography({ artistId }) {
      return request(api(`/music/artists/${encodeURIComponent(artistId)}/sync-discography/`), {
        method: 'POST',
      });
    },
    deleteArtistPlays({ artistId }) {
      return request(api(`/music/artists/${encodeURIComponent(artistId)}/plays/`), {
        method: 'DELETE',
      });
    },
    loadAlbum({ albumId }) {
      return request(albumPath(albumId));
    },
    loadAlbumTracks({ albumId }) {
      return request(api(`/music/albums/${encodeURIComponent(albumId)}/tracks/`));
    },
    saveAlbum({ albumId, ...fields }) {
      return request(albumPath(albumId), {
        method: 'PATCH',
        json: trackerFields(fields),
      });
    },
    removeAlbum({ albumId }) {
      return request(albumPath(albumId), { method: 'DELETE' });
    },
    deleteAlbumPlays({ albumId }) {
      return request(api(`/music/albums/${encodeURIComponent(albumId)}/plays/`), {
        method: 'DELETE',
      });
    },
    addListen({ albumId, trackId, endDate }) {
      return request(api('/music/songs/plays/'), {
        method: 'POST',
        json: {
          album_id: albumId,
          ...(trackId == null ? {} : { track_id: trackId }),
          ...(endDate ? { end_date: endDate } : {}),
        },
      });
    },
    rateTrack({ musicId, score }) {
      return request(api(`/music/tracks/${encodeURIComponent(musicId)}/score/`), {
        method: 'PATCH',
        json: { score },
      });
    },
    loadShow({ showId }) {
      return request(showPath(showId));
    },
    loadEpisodes({ showId, limit = 20, offset = 0 }) {
      const query = `?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`;
      return request(api(`/podcasts/shows/${encodeURIComponent(showId)}/episodes/${query}`));
    },
    saveShow({ showId, ...fields }) {
      return request(showPath(showId), {
        method: 'PATCH',
        json: trackerFields(fields),
      });
    },
    removeShow({ showId }) {
      return request(showPath(showId), { method: 'DELETE' });
    },
    addEpisodePlay({ showId, episodeId, episodeUuid, endDate }) {
      return request(api('/podcasts/episodes/plays/'), {
        method: 'POST',
        json: {
          show_id: showId,
          ...(episodeId == null ? {} : { episode_id: episodeId }),
          ...(episodeUuid ? { episode_uuid: episodeUuid } : {}),
          ...(endDate ? { end_date: endDate } : {}),
        },
      });
    },
    markAllPlayed({ showId }) {
      return request(api(`/podcasts/shows/${encodeURIComponent(showId)}/mark-all-played/`), {
        method: 'POST',
      });
    },
  };
}

export function createLocalMusicActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    loadArtist: local,
    saveArtist: local,
    removeArtist: local,
    syncArtistDiscography: local,
    deleteArtistPlays: local,
    loadAlbum: local,
    loadAlbumTracks: local,
    saveAlbum: local,
    removeAlbum: local,
    deleteAlbumPlays: local,
    addListen: local,
    rateTrack: local,
    loadShow: local,
    loadEpisodes: local,
    saveShow: local,
    removeShow: local,
    addEpisodePlay: local,
    markAllPlayed: local,
  };
}
