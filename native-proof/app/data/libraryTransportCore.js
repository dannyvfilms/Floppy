const STATUS_LABELS = {
  0: 'Planning',
  1: 'In progress',
  2: 'Paused',
  3: 'Completed',
  4: 'Dropped',
};

const STATUS_RANK = {
  Planning: 0,
  'In progress': 1,
  Completed: 2,
  Paused: 3,
  Dropped: 4,
};

const MEDIA_LABELS = {
  movie: 'Movie',
  tv: 'Show',
  season: 'Season',
  episode: 'Episode',
  anime: 'Anime',
  book: 'Book',
  comic: 'Comic',
  manga: 'Manga',
  game: 'Game',
  boardgame: 'Board Game',
  music: 'Music',
  podcast: 'Podcast',
  video: 'Video',
};

function numericDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.getUTCFullYear() * 10000 + (date.getUTCMonth() + 1) * 100 + date.getUTCDate();
}

function dateLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function yearLabel(value) {
  if (!value) return '';
  const year = new Date(value).getUTCFullYear();
  return Number.isNaN(year) ? '' : String(year);
}

function runtimeLabel(item) {
  if (item.runtime) return String(item.runtime);
  const minutes = Number(item.runtime_minutes);
  if (!Number.isFinite(minutes) || minutes <= 0) return '';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}m`;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function progressText(row, unit) {
  const progress = row.progress;
  if (progress == null) return { text: '', maxText: '' };
  if (unit === 'plays') {
    return { text: String(progress), maxText: progress === 1 ? ' play' : ' plays' };
  }
  if (unit === 'minutes') {
    const minutes = Number(progress);
    if (!Number.isFinite(minutes)) return { text: String(progress), maxText: '' };
    const hours = Math.floor(minutes / 60);
    const rest = Math.round(minutes % 60);
    const label = hours ? `${hours}h${rest ? ` ${rest}m` : ''}` : `${rest}m`;
    return { text: label, maxText: ' played' };
  }
  if (unit === 'pages' || unit === 'chapters' || unit === 'issues') {
    return { text: String(progress), maxText: ` ${unit}` };
  }
  if (unit === 'percent') {
    return { text: `${progress}%`, maxText: '' };
  }
  const left = row.episodes_left;
  if (left != null) {
    return { text: String(progress), maxText: ` / ${Number(progress) + Number(left)} episodes` };
  }
  return { text: String(progress), maxText: ' episodes' };
}

export function mediaRowFromPayload(row) {
  const item = row.item || {};
  const mediaType = item.library_media_type || item.media_type || '';
  const status = STATUS_LABELS[row.status] || '';
  const progress = progressText(row, row.progress_unit);
  const release = item.release_datetime;
  const genres = Array.isArray(item.genres) ? item.genres : [];
  const id = row.item_id || String(row.id || '');
  const title = item.title || '';
  return {
    id,
    title,
    identity: {
      mediaType,
      source: item.source,
      mediaId: item.media_id,
      libraryMediaType: item.library_media_type,
      itemId: row.id,
      title,
      image: item.image || null,
    },
    sort: {
      score: row.score == null ? null : Number(row.score),
      progress: typeof row.progress === 'number' ? row.progress : null,
      status: STATUS_RANK[status] ?? null,
      runtime: item.runtime_minutes ?? null,
      time_watched: null,
      release_date: numericDate(release),
      date_added: numericDate(row.created_at),
      genres: genres.join(', '),
    },
    track: {
      mediaType,
      progressLabel: row.progress_unit === 'minutes' ? 'Minutes played'
        : row.progress_unit === 'pages' ? 'Pages read'
          : row.progress_unit === 'plays' ? 'Times watched'
            : 'Progress',
      progressValue: row.progress == null ? '' : String(row.progress),
      progressMax: row.episodes_left != null && row.progress != null
        ? Number(row.progress) + Number(row.episodes_left)
        : null,
      startDate: row.start_date || '',
      endDate: row.end_date || '',
    },
    cells: {
      image: { kind: 'image', src: item.image || null, alt: title },
      title: { kind: 'title', text: title, href: `#open:${id}` },
      media_type: { kind: 'text', text: MEDIA_LABELS[mediaType] || mediaType, muted: true },
      score: {
        kind: 'score',
        rated: row.score != null,
        text: row.score == null ? '' : String(row.score),
      },
      progress: { kind: 'progress', text: progress.text, maxText: progress.maxText, note: 'Total' },
      status: { kind: 'status', text: status || '—', muted: !status },
      runtime: { kind: 'text', text: runtimeLabel(item) || '—', muted: !runtimeLabel(item) },
      time_watched: { kind: 'text', text: '—', muted: true },
      release_date: { kind: 'text', text: yearLabel(release) || '—', muted: !release },
      date_added: { kind: 'text', text: dateLabel(row.created_at) || '—', muted: !row.created_at },
      genres: { kind: 'genres', items: genres.map(label => ({ label })) },
    },
    media: row,
  };
}

export function mediaRowsFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results || [];
  return results.map(mediaRowFromPayload);
}

export function libraryQuery({ mediaType, limit = 30, offset = 0, search, status, sort, direction } = {}) {
  const query = { limit, offset };
  if (search) query.search = search;
  if (status) query.status = status;
  if (sort) query.sort = sort;
  if (direction) query.direction = direction;
  return query;
}

export function libraryPath(mediaType) {
  return mediaType ? `/api/v1/media/${encodeURIComponent(mediaType)}/` : '/api/v1/media/';
}

export function createRemoteLibraryActions(request) {
  return {
    mode: 'server',
    load(params = {}) {
      return request(libraryPath(params.mediaType), { query: libraryQuery(params) });
    },
    update({ identity, values = {} } = {}) {
      const mediaType = identity?.mediaType;
      const source = identity?.source;
      const mediaId = identity?.mediaId;
      if (!mediaType || !source || !mediaId) {
        return Promise.reject(new Error('This row has no provider identity to update.'));
      }
      const body = {};
      if (values.status !== undefined) body.status = values.status || null;
      if (values.score !== undefined) body.score = values.score === '' ? null : values.score;
      if (values.progress !== undefined) body.progress = values.progress === '' ? null : values.progress;
      if (values.start_date !== undefined) body.start_date = values.start_date || null;
      if (values.end_date !== undefined) body.end_date = values.end_date || null;
      return request(
        `/api/v1/media/${encodeURIComponent(mediaType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}/`,
        { method: 'PATCH', body },
      );
    },
    remove({ identity } = {}) {
      const mediaType = identity?.mediaType;
      const source = identity?.source;
      const mediaId = identity?.mediaId;
      if (!mediaType || !source || !mediaId) {
        return Promise.reject(new Error('This row has no provider identity to delete.'));
      }
      return request(
        `/api/v1/media/${encodeURIComponent(mediaType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}/`,
        { method: 'DELETE' },
      );
    },
  };
}

export function createLocalLibraryActions(reason) {
  return {
    mode: 'local',
    reason,
    load: async () => ({ local: true, reason }),
    update: async () => ({ local: true, reason }),
    remove: async () => ({ local: true, reason }),
  };
}