import { getActiveAuthSession } from './authSession.js';

const NOW_PLAYING_PATH = '/api/v1/playback/now-playing/';

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
    id: `${payload.source || 'media'}-${payload.media_id || payload.title}`,
    title: payload.title,
    episodeCode: payload.episode_code || '',
    episodeTitle: payload.episode_title || payload.title,
    subtitleLine: payload.subtitle || (payload.release_year ? String(payload.release_year) : ''),
    href: payload.url || '',
    image,
    status: payload.status === 'paused' ? 'paused' : 'playing',
    offsetSeconds: offset,
    durationSeconds: duration,
    updatedAtSeconds: Number.isFinite(updatedAt) ? Math.floor(updatedAt / 1000) : 0,
    staleAfterSeconds: 45 * 60,
    progressPercent: Number(payload.progress_percent) || 0,
    checkin: true,
  };
}

export function createPlaybackTransport({ auth } = {}) {
  const session = auth || getActiveAuthSession();
  if (!session || typeof session.request !== 'function') return null;
  return {
    mode: 'server',
    load() {
      return session.request(NOW_PLAYING_PATH).then(payload => {
        const card = playbackCardFromPayload(payload);
        return card ? [card] : [];
      });
    },
  };
}