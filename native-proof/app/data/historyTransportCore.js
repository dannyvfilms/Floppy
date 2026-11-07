const HISTORY_PATH = '/api/v1/history/';

const VERBS = {
  tv: 'Watched',
  episode: 'Watched',
  movie: 'Watched',
  anime: 'Watched',
  video: 'Watched',
  season: 'Watched',
  manga: 'Read',
  book: 'Read',
  comic: 'Read',
  game: 'Played',
  boardgame: 'Played',
  music: 'Listened',
  podcast: 'Listened',
};

function entryDate(value) {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})?/.exec(String(value || ''));
  return {
    date: match?.[1] || '',
    time: match?.[2] || '00:00',
  };
}

function payloadDays(payload) {
  if (Array.isArray(payload?.results)) return payload.results;
  if (Array.isArray(payload?.days)) return payload.days;
  if (Array.isArray(payload)) return payload;
  return [];
}

function entryNote(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}

// The native feature boundary maps the fork's bounded History REST route.
// Presentation receives plain feed values; credentials, CSRF, base URL and
// error handling stay in the request adapter behind this contract.
export function historyQuery(params = {}) {
  const query = {};
  if (params.mediaTypes?.length) query.media_type = params.mediaTypes.join(',');
  if (params.from) query.start_date = params.from;
  if (params.to) query.end_date = params.to;
  if (params.genre) query.genre = params.genre;
  if (params.impliedGenre) query.implied_genre = params.impliedGenre;
  if (params.loggingStyle) query.logging_style = params.loggingStyle;
  if (params.limit !== undefined) query.limit = params.limit;
  if (params.offset !== undefined) query.offset = params.offset;
  if (params.maxEntriesPerDay !== undefined) {
    query.max_entries_per_day = params.maxEntriesPerDay;
  }
  return query;
}

export function historyEntriesFromPayload(payload) {
  return payloadDays(payload).flatMap((day, dayIndex) => {
    const dayDate = entryDate(day.date || day.day_key);
    return (day.entries || []).map((entry, entryIndex) => {
      const played = entryDate(entry.played_at_local);
      const date = played.date || dayDate.date;
      const time = played.time;
      const mediaType = entry.media_type || entry.item?.media_type || 'movie';
      const title = entry.display_title
        || entry.title
        || entry.item?.title
        || '';
      const runtime = entry.runtime_display || entry.progress_display || '';
      const session = {
        key: `${entry.entry_key || entryIndex}-session`,
        date,
        when: entry.played_at_local
          ? String(entry.played_at_local).replace('T', ' ').slice(0, 16)
          : `${date} ${time}`,
        label: VERBS[mediaType] || 'Watched',
        runtime,
        runtimeMinutes: entry.runtime_minutes || 0,
        score: entry.score ?? null,
        note: entryNote(entry.notes),
      };
      return {
        key: entry.entry_key || `${day.date || dayIndex}-${entryIndex}`,
        historyId: entry.history_id ?? entry.instance_id ?? null,
        instanceId: entry.instance_id ?? null,
        date,
        time,
        when: session.when,
        whenValue: `${date}T${time}`,
        verb: VERBS[mediaType] || 'Watched',
        mediaType,
        title,
        subtitle: entry.episode_label || entry.episode_code || entry.show?.title || '',
        runtime,
        runtimeMinutes: entry.runtime_minutes || 0,
        score: entry.score ?? null,
        status: entry.status || null,
        genres: entry.genres || entry.item?.genres || [],
        releaseDate: entry.item?.release_date || '',
        href: entry.url || '',
        item: entry.item || null,
        image: {
          src: entry.poster || entry.item?.image || null,
          fallback: '',
          source: 'primary',
        },
        canViewActivity: true,
        canEdit: false,
        canDelete: false,
        sessions: [session],
      };
    });
  });
}

export function createRemoteHistoryActions(request) {
  return {
    mode: 'server',
    load(params = {}) {
      return request(HISTORY_PATH, { query: historyQuery(params) });
    },
    deleteRecord({ mediaType, historyId }) {
      return request(
        `/api/v1/history/${encodeURIComponent(mediaType)}/${encodeURIComponent(historyId)}/`,
        { method: 'DELETE' },
      );
    },
  };
}

export function createLocalHistoryActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    load: local,
    deleteRecord: local,
  };
}
