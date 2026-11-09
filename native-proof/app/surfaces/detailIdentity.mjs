export function identityFromDetailItem(item) {
  const supplied = item?.identity || {};
  const mediaType = supplied.mediaType || supplied.media_type || item?.mediaType || item?.media_type;
  const source = supplied.source || item?.source;
  const mediaId = supplied.mediaId || supplied.media_id || item?.mediaId || item?.media_id;
  if (mediaType && source && mediaId) {
    return {
      mediaType,
      ...(supplied.detailType || supplied.detail_type ? { detailType: supplied.detailType || supplied.detail_type } : {}),
      source,
      mediaId,
      ...(supplied.seasonNumber != null || supplied.season_number != null
        ? { seasonNumber: supplied.seasonNumber ?? supplied.season_number } : {}),
      ...(supplied.episodeNumber != null || supplied.episode_number != null
        ? { episodeNumber: supplied.episodeNumber ?? supplied.episode_number } : {}),
      publicView: Boolean(item?.publicView || item?.public_view),
    };
  }

  const href = String(item?.href || item?.url || '');
  let parsed;
  try { parsed = new URL(href, 'https://floppy.invalid'); } catch { parsed = null; }
  const path = parsed?.pathname || href;
  const publicView = parsed?.searchParams.get('public_view') === '1';
  const musicTrack = path.match(/\/details\/music\/artist\/(\d+).*?\/album\/(\d+).*?\/track\/(\d+)/);
  if (musicTrack) return { musicKind: 'track', artistId: musicTrack[1], albumId: musicTrack[2], musicId: musicTrack[3], href, publicView };
  const musicAlbum = path.match(/\/details\/music\/artist\/(\d+).*?\/album\/(\d+)/);
  if (musicAlbum) return { musicKind: 'album', artistId: musicAlbum[1], musicId: musicAlbum[2], href, publicView };
  const musicArtist = path.match(/\/details\/music\/artist\/(\d+)/);
  if (musicArtist) return { musicKind: 'artist', musicId: musicArtist[1], href, publicView };
  const podcast = path.match(/\/podcast\/show\/(\d+)/);
  if (podcast) return { podcastId: podcast[1], href, publicView };
  const episode = path.match(/^\/details\/([^/]+)\/(tv|anime)\/([^/]+)\/[^/]+\/season\/(\d+)\/episode\/(\d+)/);
  if (episode) return {
    source: episode[1], mediaType: episode[2], mediaId: episode[3],
    detailType: 'episode', seasonNumber: Number(episode[4]), episodeNumber: Number(episode[5]), href, publicView,
  };
  const season = path.match(/^\/details\/([^/]+)\/(tv|anime)\/([^/]+)\/[^/]+\/season\/(\d+)/);
  if (season) return {
    source: season[1], mediaType: season[2], mediaId: season[3],
    detailType: 'season', seasonNumber: Number(season[4]), href, publicView,
  };
  const match = path.match(/^\/details\/([^/]+)\/([^/]+)\/([^/]+)/);
  if (match) return { source: match[1], mediaType: match[2], mediaId: match[3], href, publicView };
  return null;
}

export function detailEndpoint(identity) {
  const path = `/api/v1/media/${encodeURIComponent(identity.mediaType)}/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/detail/`;
  const params = new URLSearchParams();
  if (identity.publicView) params.set('public_view', '1');
  if (identity.detailType) params.set('detail_type', identity.detailType);
  if (identity.seasonNumber != null) params.set('season_number', String(identity.seasonNumber));
  if (identity.episodeNumber != null) params.set('episode_number', String(identity.episodeNumber));
  if (identity.episodePage != null) params.set('episode_page', String(identity.episodePage));
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function detailGalleryEndpoint(identity) {
  const path = `/api/v1/media/${encodeURIComponent(identity.mediaType)}/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/detail/gallery/`;
  const params = new URLSearchParams();
  if (identity.seasonNumber != null) params.set('season_number', String(identity.seasonNumber));
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
