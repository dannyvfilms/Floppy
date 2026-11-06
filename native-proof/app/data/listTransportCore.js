const listPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/`;
const listItemPath = (listId, itemId) => (
  `${listPath(listId)}items/${encodeURIComponent(itemId)}/`
);
const smartRulesPath = listId => `/list/${encodeURIComponent(listId)}/smart-rules`;
const tierPath = (listId, action) => `/list/${encodeURIComponent(listId)}/tiers/${action}`;
const apiMediaPath = item => (
  `/api/v1/media/${encodeURIComponent(item.mediaType)}/`
  + `${encodeURIComponent(item.source)}/`
  + `${encodeURIComponent(item.mediaId)}/`
);


const STATUS_LABELS = {
  0: 'Planning', 1: 'In progress', 2: 'Paused', 3: 'Completed', 4: 'Dropped',
};
const MEDIA_LABELS = {
  movie: 'Movie', tv: 'Show', anime: 'Anime', book: 'Book', comic: 'Comic',
  manga: 'Manga', game: 'Game', boardgame: 'Board Game', music: 'Music',
  podcast: 'Podcast', video: 'Video', season: 'Season', episode: 'Episode',
};

function isoDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
}

function shortDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function yearOf(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : String(date.getUTCFullYear());
}

function progressLabel(entry) {
  const unit = entry.progress_unit;
  const progress = entry.progress;
  if (progress == null) return '';
  if (unit === 'minutes') {
    const minutes = Number(progress);
    if (!Number.isFinite(minutes)) return String(progress);
    const hours = Math.floor(minutes / 60);
    const rest = Math.round(minutes % 60);
    return `${hours ? `${hours}h${rest ? ` ${rest}m` : ''}` : `${rest}m`} played`;
  }
  if (unit === 'plays') return `${progress} ${Number(progress) === 1 ? 'play' : 'plays'}`;
  if (unit === 'pages') return `${progress} pages`;
  if (unit === 'chapters') return `${progress} chapters`;
  if (unit === 'issues') return `${progress} issues`;
  if (entry.episodes_left != null) return `${progress} / ${Number(progress) + Number(entry.episodes_left)} episodes`;
  return `${progress} ${unit || ''}`.trim();
}

export function listItemsFromPayload(payload) {
  const raw = payload?.items;
  const results = Array.isArray(raw) ? raw : raw?.results || [];
  return results.map((entry, index) => {
    const item = entry.item || {};
    const mediaType = item.library_media_type || item.media_type || '';
    const status = STATUS_LABELS[entry.status] || null;
    const score = entry.score == null ? null : Number(entry.score);
    return {
      id: entry.item_id || String(entry.id || index),
      itemId: entry.id,
      title: item.title || '',
      mediaType,
      mediaTypeLabel: MEDIA_LABELS[mediaType] || mediaType,
      source: item.source,
      mediaId: item.media_id,
      status,
      statusLabel: status,
      score,
      progressLabel: progressLabel(entry),
      releaseLabel: yearOf(item.release_datetime),
      releaseDate: isoDate(item.release_datetime),
      addedLabel: shortDate(entry.created_at),
      addedDate: isoDate(entry.created_at),
      startDateLabel: shortDate(entry.start_date),
      endDateLabel: shortDate(entry.end_date),
      rank: index + 1,
      cardShape: ['music', 'podcast'].includes(mediaType)
        ? 'square'
        : ['game', 'video'].includes(mediaType) ? 'landscape' : 'poster',
      image: { src: item.image || null, fallback: '', source: 'primary' },
      identity: {
        mediaType,
        source: item.source,
        mediaId: item.media_id,
        title: item.title || '',
      },
      rating: score == null ? null : { label: String(score), value: score, scaleMax: 10 },
      tier: '',
      tierRank: index + 1,
    };
  });
}

function memberIds(members, role) {
  return members
    .filter(member => member.role === role)
    .map(member => member.id);
}

export function createRemoteListActions(request) {
  return {
    mode: 'server',
    load({ search = '', sort = '' } = {}) {
      const query = {};
      if (search) query.search = search;
      if (sort) query.sort = sort;
      return request('/api/v1/lists/', { query: { ...query, limit: 200, offset: 0 } });
    },
    loadDetail({ listId }) {
      return request(listPath(listId), { query: { limit: 200, offset: 0 } });
    },
    create({ name, description = '', visibility, isPublic, allowRecommendations, collaborators = [], viewers = [] } = {}) {
      return request('/api/v1/lists/', {
        method: 'POST',
        json: {
          name,
          description,
          visibility,
          is_public: Boolean(isPublic),
          allow_recommendations: Boolean(allowRecommendations),
          collaborators,
          viewers,
        },
      });
    },
    update({ listId, name, description, visibility, isPublic, allowRecommendations } = {}) {
      const body = {};
      if (name !== undefined) body.name = name;
      if (description !== undefined) body.description = description;
      if (visibility !== undefined) body.visibility = visibility;
      if (isPublic !== undefined) body.is_public = Boolean(isPublic);
      if (allowRecommendations !== undefined) body.allow_recommendations = Boolean(allowRecommendations);
      return request(listPath(listId), { method: 'PATCH', json: body });
    },
    remove({ listId }) {
      return request(listPath(listId), { method: 'DELETE' });
    },
    updateVisibility({ listId, visibility }) {
      return request(listPath(listId), {
        method: 'PATCH',
        json: { visibility },
      });
    },
    setCollaborators({ listId, members }) {
      return request(listPath(listId), {
        method: 'PATCH',
        json: {
          collaborators: memberIds(members, 'collaborator'),
          viewers: memberIds(members, 'viewer'),
        },
      });
    },
    removeItem({ listId, itemId }) {
      return request(listItemPath(listId, itemId), { method: 'DELETE' });
    },
    rateItem({ item, score }) {
      return request(apiMediaPath(item), { method: 'PATCH', json: { score } });
    },
    saveSmartRules({ listId, rules }) {
      return request(smartRulesPath(listId), { method: 'POST', json: rules });
    },
    moveTierItem({ listId, itemId, tierId, itemIds = [] }) {
      return request(tierPath(listId, 'move'), {
        method: 'POST',
        form: { tier: tierId, item_id: itemId, 'item_ids[]': itemIds },
      });
    },
    saveTiers({ listId, tiers }) {
      return request(tierPath(listId, 'save'), { method: 'POST', json: { tiers } });
    },
    fillFromRatings({ listId }) {
      return request(tierPath(listId, 'fill'), { method: 'POST' });
    },
    undoTierFill({ listId, placements }) {
      return request(tierPath(listId, 'fill/undo'), { method: 'POST', json: { placements } });
    },
    bulkStatus({ itemIds, status }) {
      return request('/bulk/status', { method: 'POST', form: { status, item_ids: itemIds } });
    },
    bulkCollection({ itemIds }) {
      return request('/bulk/collection', { method: 'POST', form: { item_ids: itemIds } });
    },
  };
}

export function createLocalListActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    load: local,
    loadDetail: local,
    create: local,
    update: local,
    remove: local,
    updateVisibility: local,
    setCollaborators: local,
    removeItem: local,
    rateItem: local,
    saveSmartRules: local,
    moveTierItem: local,
    saveTiers: local,
    fillFromRatings: local,
    undoTierFill: local,
    bulkStatus: local,
    bulkCollection: local,
  };
}
