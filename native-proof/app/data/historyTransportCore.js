const HISTORY_PATH = '/api/v1/history/';
const GENRE_OPTIONS_PATH = '/api/v1/history/genres/';
const SESSIONS_PATH = '/api/v1/history/sessions/';
const RELEASE_PATH = '/api/v1/history/release/';
const SAVED_VIEWS_PATH = '/api/v1/history/saved-views/';

// The feed entry is the tracked row (its instance id), so edit and delete go
// through /api/v1/history/entries/. Only play-per-instance types can be
// deleted and every type but TV rows has a dated row to edit, the same split
// the server enforces.
const DELETABLE_TYPES = new Set(['movie', 'episode', 'game', 'boardgame']);
const EDITABLE_FIELDS = {
  episode: ['date'],
  movie: ['date', 'score', 'status'],
  anime: ['date', 'score', 'status'],
  manga: ['date', 'score', 'status'],
  game: ['date', 'score', 'status'],
  book: ['date', 'score', 'status'],
  comic: ['date', 'score', 'status'],
  boardgame: ['date', 'score', 'status'],
};

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

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];
const MONTH_NAMES_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul',
  'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function entryDate(value) {
  const match = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(String(value || ''));
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

function monthKey(date = new Date()) {
  return { year: date.getFullYear(), month: date.getMonth() + 1 };
}

function monthPrefix(cursor) {
  return `${cursor.year}-${String(cursor.month).padStart(2, '0')}`;
}

function shiftMonth(cursor, delta) {
  const index = cursor.year * 12 + (cursor.month - 1) + delta;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

function monthBounds(cursor) {
  const lastDay = new Date(Date.UTC(cursor.year, cursor.month, 0)).getUTCDate();
  return {
    from: `${monthPrefix(cursor)}-01`,
    to: `${monthPrefix(cursor)}-${String(lastDay).padStart(2, '0')}`,
  };
}

function todayKey(date = new Date()) {
  return monthPrefix(monthKey(date))
    + `-${String(date.getDate()).padStart(2, '0')}`;
}

// The web month header: full month name centered, back-one-year and
// previous-month on the past side, next-month (blocked at the current month)
// and current-month on the present side (src/app/history_views.py:1291-1322).
function historyMonthNav(cursor, now = new Date()) {
  const current = monthKey(now);
  const atCurrent = cursor.year === current.year && cursor.month === current.month;
  return {
    monthLabel: MONTH_NAMES[cursor.month - 1],
    previousYear: { label: String(cursor.year - 1) },
    previousMonth: { label: MONTH_NAMES_SHORT[shiftMonth(cursor, -1).month - 1] },
    nextMonth: { label: MONTH_NAMES_SHORT[shiftMonth(cursor, 1).month - 1], disabled: atCurrent },
    currentMonth: { label: String(current.year), disabled: atCurrent },
  };
}

// The native feature boundary maps the fork's bounded History REST route.
// Presentation receives plain feed values; credentials, CSRF, base URL and
// error handling stay in the request adapter behind this contract.
// Filters a link into History can carry (People's "View Plays in History",
// an album or artist's history): the same keys the web page reads from its
// query string. Accepts a URL, a "?a=b" string or a plain object.
const SCOPE_FILTER_KEYS = [
  'album', 'artist', 'tv', 'season', 'season_number', 'episode_number', 'podcast_show',
  'media_type', 'media_id', 'source', 'person_source', 'person_id', 'logging_style',
];

export function parseHistoryFilterUrl(value) {
  if (!value) return {};
  let search = value;
  if (typeof value === 'string') {
    const at = value.indexOf('?');
    search = new URLSearchParams(at >= 0 ? value.slice(at + 1) : value);
  } else if (!(value instanceof URLSearchParams)) {
    search = new URLSearchParams(Object.entries(value));
  }
  const scope = {};
  SCOPE_FILTER_KEYS.forEach(key => {
    const found = search.get(key);
    if (found) scope[key] = found;
  });
  return scope;
}

export function historyQuery(params = {}) {
  const query = { ...(params.scope || {}) };
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

function mapEntries(day, dayIndex) {
  const dayDate = entryDate(day.date || day.day_key);
  return (day.entries || []).map((entry, entryIndex) => {
    const played = entryDate(entry.played_at_local);
    const date = played.date || dayDate.date;
    const time = played.time;
    const mediaType = entry.media_type || entry.item?.media_type || 'movie';
    const editFields = EDITABLE_FIELDS[mediaType] || null;
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
      album: entry.album || null,
      show: entry.show || null,
      canViewActivity: true,
      editFields,
      canEdit: Boolean(editFields) && entry.instance_id != null,
      canDelete: DELETABLE_TYPES.has(mediaType) && entry.instance_id != null,
      sessions: [session],
    };
  });
}

export function historyEntriesFromPayload(payload) {
  return payloadDays(payload).flatMap(mapEntries);
}

// Days keep the server's own label, runtime and overflow counts so a day with
// more entries than the page cap can offer "load more" from the day route.
export function historyDaysFromPayload(payload) {
  return payloadDays(payload).map((day, index) => {
    const entries = mapEntries(day, index);
    const count = Number(day.entry_count ?? entries.length);
    const loaded = entries.length;
    const date = entryDate(day.date || day.day_key).date;
    const runtime = String(day.total_runtime_display || '');
    return {
      key: date || `day-${index}`,
      date,
      weekday: day.weekday || '',
      dateLabel: day.date_display || date,
      entryCount: Number.isFinite(count) ? count : loaded,
      releaseCount: day.release_count,
      runtimeLabel: /^0\s*min$/.test(runtime) ? '' : runtime,
      entries,
      hasMore: count > loaded,
      remaining: Math.max(count - loaded, 0),
    };
  });
}

function entryPath(mediaType, instanceId) {
  return `/api/v1/history/entries/${encodeURIComponent(mediaType)}/${encodeURIComponent(instanceId)}/`;
}

// The same filters the web page builds for an item's activity dialog.
export function sessionQuery(entry) {
  const item = entry.item || {};
  const query = {};
  if (entry.mediaType === 'music' && entry.album?.id) {
    query.album = entry.album.id;
  } else if (entry.mediaType === 'podcast' && entry.show?.id) {
    query.media_type = 'podcast';
    query.podcast_show = entry.show.id;
  } else if (entry.mediaType === 'episode') {
    query.media_type = 'tv';
    query.media_id = item.media_id;
    query.source = item.source;
    if (item.season_number) query.season_number = item.season_number;
  } else {
    query.media_type = entry.mediaType;
    query.media_id = item.media_id;
    query.source = item.source;
  }
  if (entry.mediaType === 'game' || entry.mediaType === 'boardgame') {
    query.logging_style = 'sessions';
  }
  return Object.fromEntries(Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ''));
}

export function historySavedViewQuery(filters = {}) {
  const params = [];
  if (filters.from) params.push(['start-date', filters.from]);
  if (filters.to) params.push(['end-date', filters.to]);
  if (filters.mediaTypes?.length) params.push(['media_type', filters.mediaTypes.join(',')]);
  if (filters.mode && filters.mode !== 'activity') params.push(['history_mode', filters.mode]);
  if (filters.genres?.length) params.push(['genre', filters.genres.join(',')]);
  if (filters.impliedGenres?.length) params.push(['implied_genre', filters.impliedGenres.join(',')]);
  return params.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&');
}

export function genreOptionsFromPayload(payload) {
  const list = (value) => (Array.isArray(value)
    ? value.map(item => String(item).trim()).filter(Boolean)
    : []);
  return {
    genres: list(payload?.genres),
    impliedGenres: list(payload?.implied_genres),
  };
}

export function createRemoteHistoryActions(request) {
  return {
    mode: 'server',
    load(params = {}) {
      return request(HISTORY_PATH, { query: historyQuery(params) });
    },
    loadGenreOptions() {
      return request(GENRE_OPTIONS_PATH).then(genreOptionsFromPayload);
    },
    loadRelease(params = {}) {
      const query = {};
      if (params.mediaTypes?.length) query.media_type = params.mediaTypes.join(',');
      if (params.from) query.start_date = params.from;
      if (params.to) query.end_date = params.to;
      if (params.genre) query.genre = params.genre;
      if (params.impliedGenre) query.implied_genre = params.impliedGenre;
      // Release days are paged by day like the main feed (bounded response).
      if (params.limit !== undefined) query.limit = params.limit;
      if (params.offset !== undefined) query.offset = params.offset;
      return request(RELEASE_PATH, { query });
    },
    loadDay({ dayKey, offset = 0, ...params }) {
      const query = { ...historyQuery(params), entry_offset: offset };
      delete query.limit;
      delete query.offset;
      return request(`/api/v1/history/days/${encodeURIComponent(dayKey.replaceAll('-', ''))}/`, { query });
    },
    loadSessions(entry) {
      return request(SESSIONS_PATH, { query: sessionQuery(entry) });
    },
    updateEntry({ mediaType, instanceId, date, score, status }) {
      const body = {};
      if (date) body.date = date;
      if (score !== undefined) body.score = score;
      if (status) body.status = status;
      return request(entryPath(mediaType, instanceId), { method: 'PATCH', body });
    },
    deleteEntry({ mediaType, instanceId }) {
      return request(entryPath(mediaType, instanceId), { method: 'DELETE' });
    },
    saveView({ name, query }) {
      return request(SAVED_VIEWS_PATH, { method: 'POST', body: { name, query } });
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
    loadGenreOptions: async () => ({ genres: [], impliedGenres: [] }),
    loadRelease: local,
    loadDay: local,
    loadSessions: local,
    updateEntry: local,
    deleteEntry: local,
    saveView: local,
    deleteRecord: local,
  };
}

export {
  monthKey,
  monthPrefix,
  shiftMonth,
  monthBounds,
  todayKey,
  historyMonthNav,
};
