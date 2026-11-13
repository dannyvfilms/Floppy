import { getActiveAuthSession } from './authSession.js';

const HOME_CARDS_PATH = '/api/v1/playback/home-cards/';
const LEGACY_NOW_PLAYING_PATH = '/api/v1/playback/now-playing/';

export function playbackDetailItem(card) {
  return {
    ...(card.href ? { href: card.href } : { identity: {
      mediaType: card.mediaType, source: card.source, mediaId: card.mediaId,
    } }),
    title: card.title,
    image: card.image,
  };
}

// Web Home hides its Now Playing row unless the server reports an active
// session. Native reads the same server state instead of seeding fixtures, so
// demo playback can never be mistaken for a real Floppy session.
export function playbackCardFromPayload(payload) {
  if (!payload || payload.active === false || !payload.title) return null;
  const offset = Number(payload.offset_seconds) || 0;
  const duration = Number(payload.duration_seconds) || 0;
  const image = typeof payload.image === 'string'
    ? { src: payload.image, alt: payload.title }
    : payload.image || null;
  const updatedAt = Date.parse(payload.updated_at || '');
  return {
    id: payload.id || `${payload.source || 'media'}-${payload.media_type || 'media'}-${payload.media_id || payload.title}`,
    source: payload.source || '',
    mediaType: payload.media_type || '',
    mediaId: String(payload.media_id || ''),
    title: payload.title,
    episodeCode: payload.episode_code || '',
    episodeTitle: payload.episode_title || '',
    subtitleLine: payload.subtitle || (payload.release_year ? String(payload.release_year) : ''),
    href: payload.url || '',
    image,
    status: ['paused', 'stopped'].includes(payload.status) ? 'paused' : 'playing',
    offsetSeconds: offset,
    durationSeconds: duration,
    updatedAtSeconds: Number.isFinite(updatedAt) ? Math.floor(updatedAt / 1000) : 0,
    staleAfterSeconds: Number(payload.stale_after_seconds) || 45 * 60,
    progressPercent: Number(payload.progress_percent) || 0,
    actions: Array.isArray(payload.actions) ? payload.actions : [],
    checkin: Array.isArray(payload.actions) && payload.actions.length > 0,
  };
}

export function playbackCardsFromPayload(payload) {
  return (Array.isArray(payload?.cards) ? payload.cards : [])
    .map(playbackCardFromPayload)
    .filter(Boolean);
}

export function createPlaybackTransport({ auth } = {}) {
  const session = auth || getActiveAuthSession();
  if (!session || typeof session.request !== 'function') return null;
  return {
    mode: 'server',
    load() {
      return session.request(HOME_CARDS_PATH).then(playbackCardsFromPayload).catch(error => {
        if (error?.status !== 404) throw error;
        // Older servers expose only the read-only single-card endpoint.
        // Keep the session visible during upgrades; controls appear once the
        // server supports the session-only Home card endpoint.
        return session.request(LEGACY_NOW_PLAYING_PATH).then(payload => {
          const card = playbackCardFromPayload(payload);
          return card ? [card] : [];
        });
      });
    },
    act(card, action) {
      return session.request(HOME_CARDS_PATH, {
        method: 'POST',
        json: {
          source: card.source,
          media_type: card.mediaType,
          media_id: card.mediaId,
          action,
        },
      });
    },
  };
}
