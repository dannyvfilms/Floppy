// Detail page server access. Every call goes through the signed-in session
// (cookie or Bearer token) against /api/v1; the pure mapping is in
// detailTransportCore.js.
import { getActiveAuthSession } from './authSession';
import { formatUserDate, loadDatePreferences } from './userDate.js';
import {
  artworkFromPayload,
  detailModelFromPayloads,
  episodeActionPath,
  episodesFromPayload,
  identityFromItem,
  issuesFromPayload,
  mediaPath,
  seasonEpisodesPath,
  seasonsFromDetail,
} from './detailTransportCore';

function call(path, options) {
  const session = getActiveAuthSession();
  if (typeof session?.request !== 'function') {
    return Promise.reject(new Error('Sign in to your Floppy server to load this page.'));
  }
  return session.request(path, options);
}

function resultList(payload) {
  if (Array.isArray(payload)) return payload;
  return payload && Array.isArray(payload.results) ? payload.results : [];
}

function settled(result) {
  return result.status === 'fulfilled' ? result.value : null;
}

/**
 * Load everything one detail page shows. The provider detail and the stored
 * metadata are the two primary reads: when both fail the page cannot render
 * more than the tapped card, so the failure is thrown for a Retry. Tracking
 * state and the parent show are secondary and only degrade the page.
 */
export async function loadDetailPage(item) {
  await loadDatePreferences(call);
  const identity = identityFromItem(item);
  if (!identity) return { identity: null, model: detailModelFromPayloads({ item }) };
  const path = mediaPath(identity);
  const seasoned = identity.mediaType === 'season' || identity.mediaType === 'episode';
  const parentIdentity = seasoned
    ? { mediaType: 'tv', source: identity.source, mediaId: identity.mediaId }
    : null;
  const [detail, metadata, state, parent, siblings, recommendations] = await Promise.allSettled([
    call(`${path}/`),
    call(`${path}/metadata/`),
    call(`${path}/state/`),
    parentIdentity ? call(`${mediaPath(parentIdentity)}/`) : Promise.resolve(null),
    identity.mediaType === 'episode'
      ? call(seasonEpisodesPath(identity, identity.seasonNumber))
      : Promise.resolve(null),
    // The detail payload leaves recommendations to their own endpoint.
    identity.mediaType === 'episode' ? Promise.resolve(null) : call(`${path}/recommendations/`),
  ]);
  if (detail.status === 'rejected' && metadata.status === 'rejected') throw detail.reason;
  const detailPayload = settled(detail);
  const parentPayload = settled(parent);
  const model = detailModelFromPayloads({
    item,
    identity,
    detail: detailPayload,
    metadata: settled(metadata),
    state: settled(state),
    recommendations: resultList(settled(recommendations)),
  });
  const seasonSource = identity.mediaType === 'tv' ? detailPayload : parentPayload;
  return {
    identity,
    model: {
      ...model,
      parent: parentPayload
        ? { title: parentPayload.title, identity: parentIdentity }
        : null,
      parentGenres: Array.isArray(parentPayload?.genres) ? parentPayload.genres : [],
      seasons: seasonSource ? seasonsFromDetail(seasonSource, parentIdentity || identity) : [],
      siblingEpisodes: siblings.status === 'fulfilled' && siblings.value
        ? episodesFromPayload(siblings.value, identity, identity.seasonNumber)
        : [],
    },
  };
}

/** One page of a comic volume's issues (the web "Issues" list). */
export async function loadIssues(identity, offset = 0, limit = 20) {
  const payload = await call(`${mediaPath(identity)}/issues/?limit=${limit}&offset=${offset}`);
  return issuesFromPayload(payload, identity);
}

export async function loadSeasonEpisodes(identity, seasonNumber) {
  const payload = await call(seasonEpisodesPath(identity, seasonNumber));
  return episodesFromPayload(payload, identity, seasonNumber);
}

export async function loadAnimeEpisodes(identity, queryString = '') {
  const payload = await call(`${mediaPath(identity)}/episode-preview/${queryString ? `?${queryString}` : ''}`);
  return { rows: episodesFromPayload(payload, identity, null), loadMore: payload.load_more || null, related: payload.related || {} };
}

export function watchEpisode(identity) {
  return call(episodeActionPath(identity, 'watch'), {
    method: 'POST',
    body: { end_date: new Date().toISOString() },
  });
}

export function dropEpisode(identity) {
  return call(episodeActionPath(identity, 'drop'), { method: 'POST', body: {} });
}

export function deleteHistoryEntry(identity, consumptionId) {
  return call(`${mediaPath(identity)}/history/${encodeURIComponent(consumptionId)}/`, {
    method: 'DELETE',
  });
}

export function saveEntryNotes(identity, consumptionId, notes) {
  return call(`${mediaPath(identity)}/history/${encodeURIComponent(consumptionId)}/`, {
    method: 'PATCH',
    body: { notes },
  });
}

export function syncMetadata(identity) {
  return call(`${mediaPath(identity)}/sync/`, { method: 'POST', body: {} });
}

function collectedLine(collected, total) {
  const percent = total > 0 ? ` \u2022 ${Math.floor((collected / total) * 100)}%` : '';
  return `${collected}/${total}${percent}`;
}

/** Owned copies plus, for shows and seasons, the web card's collected counts. */
export async function loadCollectionEntries(identity) {
  const payload = await call(`${mediaPath(identity)}/collection/entries/`);
  const stats = payload?.stats;
  const counts = [];
  if (stats && identity.mediaType !== 'season' && identity.mediaType !== 'episode') {
    counts.push({ label: 'COLLECTED SEASONS', value: collectedLine(stats.collected_seasons || 0, stats.total_seasons || 0) });
  }
  if (stats) {
    counts.push({ label: 'COLLECTED EPISODES', value: collectedLine(stats.collected_episodes || 0, stats.total_episodes || 0) });
  }
  return {
    counts,
    entries: resultList(payload).map(entry => ({
      id: String(entry.id),
      title: [entry.media_type, entry.resolution, entry.hdr, entry.is_3d ? '3D' : '']
        .filter(Boolean)
        .join(' \u00b7 ') || 'Owned copy',
      date: formatUserDate(entry.collected_at),
    })),
  };
}

/**
 * The "Your Progress" card and breakdown of a tracked season; null when not
 * tracked. The web show page renders no card (its tracker carries no total).
 */
export async function loadProgressCard(identity) {
  if (identity.mediaType !== 'season' && identity.mediaType !== 'tv') return null;
  try {
    return await call(`${mediaPath(identity)}/progress-card/`);
  } catch (error) {
    if (error && error.status === 404) return null;
    throw error;
  }
}

/** Seerr state, or null when Seerr is not configured for this account. */
export async function loadSeerr(identity) {
  try {
    return await call(`${mediaPath(identity)}/request/`);
  } catch (error) {
    if (error && error.status === 404) return null;
    throw error;
  }
}

export function requestSeerr(identity, seasons) {
  return call(`${mediaPath(identity)}/request/`, {
    method: 'POST',
    body: seasons && seasons.length ? { seasons } : {},
  });
}

/** The web Check-in split button's actions for the tracked entry, or null when it offers none. */
export async function loadCheckIn(identity) {
  if (!identity || identity.mediaType === 'season' || identity.mediaType === 'episode') return null;
  try {
    return await call(`${mediaPath(identity)}/checkin/`);
  } catch (error) {
    if (error && error.status === 404) return null;
    throw error;
  }
}

/** Run one Check-in action (start, resume, pause, finish, stop, cancel, log_play); returns the new actions. */
export function runCheckIn(identity, action) {
  return call(`${mediaPath(identity)}/checkin/`, { method: 'POST', body: { action } });
}

const ARTWORK_TYPES = new Set(['movie', 'tv', 'season', 'game']);
const NO_SCORES = { chips: [], graphs: {}, gameLengths: null };

/** Backdrop hero, title logo, trailer and gallery; null when the source has none. */
export async function loadArtwork(identity) {
  if (!identity || !ARTWORK_TYPES.has(identity.mediaType)) return null;
  try {
    // The gallery belongs to the show; a season names itself in the query.
    const { mediaType, source, mediaId, seasonNumber } = identity;
    const season = mediaType === 'season' && seasonNumber != null;
    const data = await call(
      `/api/v1/media/${encodeURIComponent(season ? 'tv' : mediaType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}/detail/gallery/`,
      season ? { query: { season_number: seasonNumber } } : undefined,
    );
    return artworkFromPayload(data?.gallery ? { available: true, ...data.gallery } : null);
  } catch {
    return null;
  }
}

/** Stored Trakt, IMDb, MAL and OpenCritic chips plus the series graphs. */
export async function loadScores(identity) {
  if (!identity) return NO_SCORES;
  if (identity.mediaType === 'episode') {
    // Episodes have no stored chips; the season's response still names the source logos.
    try {
      const season = await call(`${mediaPath({ ...identity, mediaType: 'season', episodeNumber: undefined })}/scores/`);
      return { ...NO_SCORES, logos: season?.logos || {} };
    } catch {
      return NO_SCORES;
    }
  }
  try {
    return await call(`${mediaPath(identity)}/scores/`);
  } catch {
    return NO_SCORES;
  }
}

/** The web "Activity History" entries, grouped by day; null when the request fails. */
export async function loadActivityTimeline(identity) {
  const seasoned = identity.mediaType === 'season' || identity.mediaType === 'episode';
  const base = mediaPath(identity);
  const payload = await call(`${base}/activity-timeline/`);
  return {
    multipleInstances: Boolean(payload?.multipleInstances),
    days: (payload?.days || []).map(day => ({
      day: day.day,
      label: day.label || day.day,
      entries: (day.entries || []).map(entry => ({
        id: String(entry.id),
        instance: entry.instance,
        date: entry.date,
        changes: entry.changes || [],
      })),
    })),
    seasoned,
  };
}

/** Covers on offer for a tracked item (Open Library by barcode, then provider search). */
export async function loadCoverCandidates(itemId) {
  const payload = await call(`/api/v1/metadata/items/${encodeURIComponent(itemId)}/cover/`);
  return { current: payload?.current || '', candidates: payload?.candidates || [] };
}

/** Store a picked file (base64) or a linked image as the item's cover. */
export function saveCover(itemId, { base64, url }) {
  return call(`/api/v1/metadata/items/${encodeURIComponent(itemId)}/cover/`, {
    method: 'POST',
    body: base64 ? { cover_base64: base64 } : { cover_url: url },
  });
}

/** Hardcover editions of a book, filtered by `query`, and the edition in use. */
export async function loadEditions(itemId, query = '') {
  const payload = await call(`/api/v1/metadata/items/${encodeURIComponent(itemId)}/hardcover-editions/`, {
    query: query ? { q: query } : undefined,
  });
  return {
    selected: payload?.selected ? String(payload.selected) : '',
    rows: (payload?.results || []).map(edition => ({
      id: String(edition.id),
      uri: edition.image || '',
      title: edition.title || '',
      meta: [[edition.language, edition.format].filter(Boolean).join(' · ')].filter(Boolean),
    })),
  };
}

export function saveEdition(itemId, editionId) {
  return call(`/api/v1/metadata/items/${encodeURIComponent(itemId)}/hardcover-editions/`, {
    method: 'POST',
    body: { edition_id: editionId },
  });
}
