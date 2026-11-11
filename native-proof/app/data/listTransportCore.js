import { formatUserDate, loadDatePreferences } from './userDate.js';
const listPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/`;
const recommendationsPath = listId => `${listPath(listId)}recommendations/`;
const tiersPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/tiers/`;
const smartRulesPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/smart-rules/`;

// The API returns at most this many rows per request, so every list or
// item page is fetched in turns of this size until the server reports the end.
export const LIST_PAGE_SIZE = 200;
const searchRoutePath = mediaType => `/api/v1/search/${encodeURIComponent(mediaType)}/`;

function mediaPath(identity) {
  const { mediaType, source, mediaId, seasonNumber, episodeNumber } = identity || {};
  const pathType = mediaType === 'episode' ? 'tv' : mediaType;
  let path = `/api/v1/media/${encodeURIComponent(pathType)}/`
    + `${encodeURIComponent(source)}/`
    + `${encodeURIComponent(mediaId)}`;
  if (seasonNumber != null) path += `/${encodeURIComponent(seasonNumber)}`;
  if (episodeNumber != null) path += `/${encodeURIComponent(episodeNumber)}`;
  return path;
}


const STATUS_LABELS = {
  0: 'Planning', 1: 'In progress', 2: 'Paused', 3: 'Completed', 4: 'Dropped',
};
const MEDIA_LABELS = {
  movie: 'Movie', tv: 'Show', anime: 'Anime', book: 'Book', comic: 'Comic',
  manga: 'Manga', game: 'Game', boardgame: 'Board Game', music: 'Music',
  podcast: 'Podcast', video: 'Video', season: 'Season', episode: 'Episode',
};

// Hub sorts the list API accepts (src/api/helpers.py LIST_SORTS). `name` is
// the only sort the web shows ascending first; the rest start descending.
// The media types a list can be filtered by (GET /lists/?media_type=), in the
// sidebar's order; "all" is the web's "All Types".
export const LIST_TYPE_OPTIONS = [
  { value: 'all', label: 'All Types' },
  { value: 'tv', label: 'TV Shows' },
  { value: 'season', label: 'TV Seasons' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'manga', label: 'Manga' },
  { value: 'game', label: 'Games' },
  { value: 'book', label: 'Books' },
  { value: 'comic', label: 'Comics' },
  { value: 'boardgame', label: 'Board Games' },
  { value: 'music', label: 'Music' },
  { value: 'podcast', label: 'Podcasts' },
  { value: 'video', label: 'Videos' },
];

export const LIST_SORT_OPTIONS = [
  { value: 'update', label: 'Last Item Added', direction: 'desc' },
  { value: 'watched', label: 'Last Watched', direction: 'desc' },
  { value: 'items', label: 'Items Count', direction: 'desc' },
  { value: 'name', label: 'Name', direction: 'asc' },
  { value: 'new', label: 'Newest First', direction: 'desc' },
];

function isoDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
}

// List membership time, not the tracking row's creation time, controls Date Added.
export function compareListDateAdded(left, right, direction = 'desc') {
  const time = value => {
    const parsed = Date.parse(value || '');
    return Number.isNaN(parsed) ? 0 : parsed;
  };
  return (time(left.addedAt) - time(right.addedAt)) * (direction === 'asc' ? 1 : -1);
}

// The web's date in the server time zone and the user's date format.
function shortDate(value) {
  return value ? formatUserDate(value) : '';
}

function shortDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function yearOf(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : String(date.getUTCFullYear());
}

function ageLabel(value) {
  if (!value) return '';
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return '';
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return 'moments';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'}`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? '' : 's'}`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} month${months === 1 ? '' : 's'}`;
  const years = Math.floor(months / 12);
  return `${years} year${years === 1 ? '' : 's'}`;
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

export function listItemsFromPayload(payload, offset = 0) {
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
      seasonNumber: item.season_number,
      episodeNumber: item.episode_number,
      status,
      statusLabel: status,
      score,
      progressLabel: progressLabel(entry),
      releaseLabel: yearOf(item.release_datetime),
      releaseDate: isoDate(item.release_datetime),
      addedAt: entry.list_date_added || entry.created_at || '',
      addedLabel: shortDate(entry.list_date_added || entry.created_at),
      addedDate: isoDate(entry.list_date_added || entry.created_at),
      startDateLabel: shortDate(entry.start_date),
      endDateLabel: shortDate(entry.end_date),
      startDate: isoDate(entry.start_date),
      endDate: isoDate(entry.end_date),
      rank: entry.rank == null ? offset + index + 1 : Number(entry.rank) || offset + index + 1,
      cardShape: ['music', 'podcast'].includes(mediaType)
        ? 'square'
        : ['game', 'video'].includes(mediaType) ? 'landscape' : 'poster',
      image: { src: item.image || null, fallback: '', source: 'primary' },
      identity: {
        mediaType,
        source: item.source,
        mediaId: item.media_id,
        title: item.title || '',
        seasonNumber: item.season_number,
        episodeNumber: item.episode_number,
      },
      rating: score == null ? null : { label: String(score), value: score, scaleMax: 10 },
      tier: '',
      tierRank: offset + index + 1,
    };
  });
}

// Whether another page follows the one just read.
export function hasMorePages(payload, offset, limit = LIST_PAGE_SIZE) {
  const pagination = payload?.pagination || payload?.items?.pagination;
  if (!pagination) return false;
  const total = Number(pagination.total);
  if (Number.isFinite(total)) return offset + limit < total;
  return Boolean(pagination.next);
}

// The pagination block of a list detail payload (items live under `items`).
export function itemsPageFromPayload(payload) {
  const raw = payload?.items;
  const results = Array.isArray(raw) ? raw : raw?.results || [];
  return { count: results.length, total: Number(raw?.pagination?.total) || results.length };
}

// Tier definitions and each item's placement from GET .../tiers/. Items are
// matched on their numeric item id; a blank or unknown tier is Unranked.
export function tiersFromPayload(payload) {
  const tiers = Array.isArray(payload?.tiers) ? payload.tiers : [];
  return tiers.map(tier => ({ id: String(tier.id), name: tier.name || '', color: tier.color || '' }));
}

export function applyTierPlacements(items, payload) {
  const tiers = tiersFromPayload(payload);
  const valid = new Set(tiers.map(tier => tier.id));
  const rankByTier = {};
  const placed = new Map();
  (Array.isArray(payload?.placements) ? payload.placements : []).forEach(entry => {
    const tier = valid.has(entry.tier) ? entry.tier : '';
    rankByTier[tier] = (rankByTier[tier] || 0) + 1;
    placed.set(String(entry.item_id), { tier, tierRank: rankByTier[tier] });
  });
  return items.map(item => {
    const placement = placed.get(String(item.itemId));
    return placement ? { ...item, ...placement } : { ...item, tier: '', tierRank: item.tierRank };
  });
}

function visibilityLabel(visibility) {
  if (visibility === 'public') return 'Public';
  if (visibility === 'unlisted') return 'Unlisted';
  return 'Private';
}

export function listSummaryFromPayload(payload, currentUsername = '') {
  if (!payload || payload.id == null) return null;
  const owner = payload.owner || {};
  const collaborators = Array.isArray(payload.collaborators) ? payload.collaborators : [];
  const viewers = Array.isArray(payload.viewers) ? payload.viewers : [];
  const isOwner = owner.username === currentUsername;
  const isCollaborator = collaborators.some(member => member.username === currentUsername);
  const members = [
    owner.id != null
      ? { id: String(owner.id), name: owner.username || '', handle: owner.username ? `@${owner.username}` : '', role: 'owner' }
      : null,
    ...collaborators.map(member => ({
      id: String(member.id),
      name: member.username || '',
      handle: member.username ? `@${member.username}` : '',
      role: 'collaborator',
    })),
    ...viewers.map(member => ({
      id: String(member.id),
      name: member.username || '',
      handle: member.username ? `@${member.username}` : '',
      role: 'viewer',
    })),
  ].filter(Boolean);
  const visibility = payload.visibility
    || (payload.is_public ? 'public' : payload.is_unlisted ? 'unlisted' : 'private');
  return {
    id: String(payload.id),
    name: payload.name || '',
    description: payload.description || '',
    coverUrl: payload.image || null,
    isSmart: Boolean(payload.is_smart),
    source: 'local',
    visibility,
    visibilityLabel: visibilityLabel(visibility),
    role: isOwner ? 'Owner' : isCollaborator ? 'Collaborator' : 'Viewer',
    isOwner,
    memberCount: members.length,
    members,
    itemsCount: Number(payload.items_count) || 0,
    completionPercent: Number.isFinite(payload.completion_percent) ? payload.completion_percent : null,
    mediaTypeBreakdown: Array.isArray(payload.media_type_breakdown)
      ? payload.media_type_breakdown.map(row => ({
        value: String(row.value || ''),
        label: String(row.label || row.value || ''),
        count: Number(row.count) || 0,
        percent: Number(row.percent) || 0,
        color: String(row.color || ''),
      }))
      : [],
    canEdit: isOwner || isCollaborator,
    canDelete: isOwner,
    canRecommend: visibility === 'public' && Boolean(payload.allow_recommendations),
    allowRecommendations: Boolean(payload.allow_recommendations),
    publicSlug: payload.public_slug || '',
    tags: Array.isArray(payload.tags) ? payload.tags.filter(tag => typeof tag === 'string') : [],
    includeNotes: Boolean(payload.include_notes),
    href: `/lists/${payload.id}`,
  };
}

export function listsFromPayload(payload, currentUsername = '') {
  const results = Array.isArray(payload) ? payload : payload?.results;
  if (!Array.isArray(results)) return [];
  return results
    .map(list => listSummaryFromPayload(list, currentUsername))
    .filter(Boolean);
}

const ACTIVITY_DESCRIPTIONS = {
  item_added: (user, item) => `${user} added ${item}`,
  item_removed: (user, item) => `${user} removed ${item}`,
  recommendation_approved: (user, item) => `${user} approved ${item}`,
  recommendation_denied: (user, item) => `${user} denied ${item}`,
  list_created: user => `${user} created the list`,
  list_edited: user => `${user} edited the list`,
  collaborator_added: user => `${user} added a collaborator`,
  collaborator_removed: user => `${user} removed a collaborator`,
};

export function activityFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results;
  if (!Array.isArray(results)) return [];
  return results.map(entry => {
    const user = entry.user || 'Someone';
    const itemTitle = entry.item_title || 'an item';
    const build = ACTIVITY_DESCRIPTIONS[entry.activity_type];
    const base = build ? build(user, itemTitle) : 'Unknown activity';
    return {
      id: entry.id,
      type: entry.activity_type || '',
      user: entry.user || '',
      itemId: entry.item_id,
      itemTitle,
      details: entry.details || '',
      description: entry.details ? `${base}: ${entry.details}` : base,
      timestampLabel: shortDateTime(entry.timestamp),
      agoLabel: ageLabel(entry.timestamp),
    };
  });
}

export function recommendationsFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results;
  if (!Array.isArray(results)) return [];
  return results.map(entry => {
    const mediaType = entry.media_type || '';
    return {
      id: String(entry.id),
      itemId: entry.item_id,
      title: entry.title || '',
      mediaType,
      mediaTypeLabel: MEDIA_LABELS[mediaType] || mediaType,
      recommender: entry.recommended_by || '',
      note: entry.note || '',
      dateLabel: ageLabel(entry.date_recommended),
      identity: {
        mediaType,
        source: entry.source,
        mediaId: entry.media_id,
        title: entry.title || '',
        seasonNumber: entry.season_number,
        episodeNumber: entry.episode_number,
      },
      media: {
        title: entry.title || '',
        image: { src: entry.image || null, fallback: '', source: 'primary' },
        shape: 'poster',
        video: false,
        href: null,
        statusChip: null,
        cornerChips: [],
        lines: [],
        rating: null,
      },
    };
  });
}

export function searchResultsFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results;
  if (!Array.isArray(results)) return [];
  return results.map(entry => {
    const mediaType = entry.media_type || '';
    return {
      id: `${mediaType}-${entry.source}-${entry.media_id}`,
      mediaType,
      mediaTypeLabel: MEDIA_LABELS[mediaType] || mediaType,
      title: entry.title || '',
      source: entry.source,
      mediaId: entry.media_id == null ? '' : String(entry.media_id),
      year: entry.year == null ? '' : String(entry.year),
      image: entry.image || null,
      platforms: Array.isArray(entry.platforms) ? entry.platforms : [],
      identity: {
        mediaType,
        source: entry.source,
        mediaId: entry.media_id == null ? '' : String(entry.media_id),
        title: entry.title || '',
      },
    };
  });
}

export function searchPaginationFromPayload(payload) {
  const pagination = payload?.pagination || {};
  const total = Number(pagination.total) || 0;
  const limit = Number(pagination.limit) || 20;
  return {
    total,
    limit,
    offset: Number(pagination.offset) || 0,
    totalPages: Math.max(1, Math.ceil(total / limit)),
  };
}

// Usernames of the members with one role; the member endpoints take names.
export function memberUsernames(members, role) {
  return (members || [])
    .filter(member => member.role === role && member.name)
    .map(member => String(member.name));
}

// Rules the smart editor works on, plus the option lists it offers.
export function smartRulesFromPayload(payload) {
  const rules = payload?.rules;
  if (!rules || typeof rules !== 'object') return null;
  return { ...rules };
}

const MEDIA_OPTION_KEYS = {
  genres: 'genres',
  implied_genres: 'impliedGenres',
  years: 'years',
  sources: 'sources',
  languages: 'languages',
  countries: 'countries',
  platforms: 'platforms',
  origins: 'origins',
  formats: 'formats',
  authors: 'authors',
  providers: 'providers',
  tags: 'tags',
  lists: 'lists',
};

export function smartOptionsFromPayload(payload) {
  const raw = payload?.options || {};
  const options = {
    mediaTypes: (payload?.media_types || []).map(entry => ({ value: entry.value, label: entry.label })),
    statuses: Object.keys(STATUS_LABELS).map(key => ({ value: STATUS_LABELS[key], label: STATUS_LABELS[key] })),
  };
  Object.entries(MEDIA_OPTION_KEYS).forEach(([from, to]) => {
    if (Array.isArray(raw[from])) options[to] = raw[from];
  });
  ['languages', 'countries', 'platforms', 'origins', 'formats', 'authors'].forEach(name => {
    const flag = `show_${name}`;
    if (flag in raw) options[`show${name[0].toUpperCase()}${name.slice(1)}`] = Boolean(raw[flag]);
  });
  if (raw.author_is_channel) options.authorIsChannel = true;
  return options;
}

// GET .../lists/ pages: fetch every page so the hub never stops at one.
async function fetchAllPages(request, path, baseQuery) {
  const results = [];
  let offset = 0;
  for (;;) {
    const payload = await request(path, { query: { ...baseQuery, limit: LIST_PAGE_SIZE, offset } });
    const rows = Array.isArray(payload) ? payload : payload?.results || [];
    results.push(...rows);
    if (!rows.length || Array.isArray(payload) || !hasMorePages(payload, offset)) break;
    offset += LIST_PAGE_SIZE;
  }
  return { results };
}

function listBody({
  name, description, visibility, isPublic, allowRecommendations, publicSlug, tags, includeNotes, isSmart,
}) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (description !== undefined) body.description = description;
  if (visibility !== undefined) body.visibility = visibility;
  if (isPublic !== undefined) body.is_public = Boolean(isPublic);
  if (allowRecommendations !== undefined) body.allow_recommendations = Boolean(allowRecommendations);
  if (publicSlug !== undefined) body.public_slug = publicSlug;
  if (tags !== undefined) body.tags = tags;
  if (includeNotes !== undefined) body.include_notes = Boolean(includeNotes);
  if (isSmart !== undefined) body.is_smart = Boolean(isSmart);
  return body;
}

export function createRemoteListActions(request) {
  return {
    mode: 'server',
    load({ search = '', sort = '', mediaType = '' } = {}) {
      const query = {};
      if (search) query.search = search;
      if (mediaType && mediaType !== 'all') query.media_type = mediaType;
      if (sort) query.sort = sort;
      return fetchAllPages(request, '/api/v1/lists/', query);
    },
    // One page of items; the caller pages on until hasMorePages says stop.
    async loadDetail({
      listId, offset = 0, limit = LIST_PAGE_SIZE, sort = '', search = '', mediaType = '',
    } = {}) {
      await loadDatePreferences(request);
      const query = { limit, offset };
      if (sort) query.sort = sort;
      if (search) query.search = search;
      if (mediaType) query.media_type = mediaType;
      return request(listPath(listId), { query });
    },
    loadActivity({ listId }) {
      return request(`${listPath(listId)}activity/`);
    },
    loadRecommendations({ listId }) {
      return request(recommendationsPath(listId));
    },
    searchMedia({ mediaType, search = '', limit = 20, offset = 0 } = {}) {
      const query = { limit, offset };
      if (search) query.search = search;
      return request(searchRoutePath(mediaType), { query });
    },
    create(fields = {}) {
      return request('/api/v1/lists/', {
        method: 'POST',
        json: { ...listBody({ ...fields, isPublic: Boolean(fields.isPublic) }), description: fields.description || '' },
      });
    },
    update({ listId, ...fields } = {}) {
      return request(listPath(listId), { method: 'PATCH', json: listBody(fields) });
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
    // Collaborators and viewers are added by username through their own
    // endpoints; an unknown name comes back as a 404 naming it.
    setMembers({ listId, collaborators, viewers }) {
      const calls = [];
      if (collaborators) {
        calls.push(request(`${listPath(listId)}collaborators/`, { method: 'PUT', json: { usernames: collaborators } }));
      }
      if (viewers) {
        calls.push(request(`${listPath(listId)}viewers/`, { method: 'PUT', json: { usernames: viewers } }));
      }
      return Promise.all(calls);
    },
    loadSmartRules({ listId }) {
      return request(smartRulesPath(listId));
    },
    loadSmartOptions({ listId }) {
      return request(`${smartRulesPath(listId)}options/`);
    },
    saveSmartRules({ listId, rules }) {
      return request(smartRulesPath(listId), { method: 'PUT', json: rules });
    },
    syncSmartList({ listId }) {
      return request(`${listPath(listId)}smart-sync/`, { method: 'POST' });
    },
    // Imports (Trakt device flow, MDBList, CSV text) and CSV export.
    loadImportStatus() {
      return request('/api/v1/lists/import/');
    },
    importCsv({ text }) {
      return request('/api/v1/lists/import/csv/', { method: 'POST', json: { text } });
    },
    importMdblist(body) {
      return request('/api/v1/lists/import/mdblist/', { method: 'POST', json: body });
    },
    importTrakt(body) {
      return request('/api/v1/lists/import/trakt/', { method: 'POST', json: body });
    },
    exportList({ listId }) {
      return request(`${listPath(listId)}export/`);
    },
    addItem({ listId, item }) {
      const identity = item.identity || item;
      const body = {};
      if (item.libraryMediaType) body.library_media_type = item.libraryMediaType;
      return request(`${mediaPath(identity)}/lists/${encodeURIComponent(listId)}/`, {
        method: 'PUT',
        json: body,
      });
    },
    removeItem({ listId, item }) {
      const identity = item.identity || item;
      return request(`${mediaPath(identity)}/lists/${encodeURIComponent(listId)}/`, {
        method: 'DELETE',
      });
    },
    rateItem({ item, score }) {
      return request(mediaPath(item.identity || item), { method: 'PATCH', json: { score } });
    },
    recommend({ listId, item, note = '' }) {
      const identity = item.identity || item;
      return request(recommendationsPath(listId), {
        method: 'POST',
        json: {
          media_id: identity.mediaId,
          media_type: identity.mediaType,
          source: identity.source,
          note,
        },
      });
    },
    decideRecommendation({ listId, recommendationId, decision }) {
      const word = decision === 'approve' ? 'approve' : 'deny';
      return request(
        `${recommendationsPath(listId)}${encodeURIComponent(recommendationId)}/${word}/`,
        { method: 'POST' },
      );
    },
    reorderItem({ listId, itemId, action }) {
      return request(`${listPath(listId)}items/reorder/`, {
        method: 'POST',
        json: { item_id: itemId, action },
      });
    },
    loadTiers({ listId }) {
      return request(tiersPath(listId));
    },
    moveTierItem({ listId, itemId, tierId, itemIds = [] }) {
      return request(`${tiersPath(listId)}move/`, {
        method: 'POST',
        json: { tier: tierId, item_id: itemId, item_ids: itemIds },
      });
    },
    saveTiers({ listId, tiers }) {
      return request(tiersPath(listId), { method: 'PUT', json: { tiers } });
    },
    fillFromRatings({ listId }) {
      return request(`${tiersPath(listId)}fill/`, { method: 'POST' });
    },
    undoTierFill({ listId, placements }) {
      return request(`${tiersPath(listId)}fill/undo/`, { method: 'POST', json: { placements } });
    },
    // Bulk actions run through the same endpoints as the Library toolbar;
    // they take numeric item ids.
    bulkStatus({ itemIds, status }) {
      return request('/api/v1/library/bulk/status/', { method: 'POST', json: { item_ids: itemIds, status } });
    },
    bulkCollection({ itemIds }) {
      return request('/api/v1/library/bulk/collection/', { method: 'POST', json: { item_ids: itemIds } });
    },
    bulkList({ itemIds, listId }) {
      return request(`/api/v1/lists/${encodeURIComponent(listId)}/items/bulk/`, {
        method: 'POST',
        json: { item_ids: itemIds },
      });
    },
    bulkTag({ itemIds, tagId }) {
      return request('/api/v1/library/bulk/tags/', {
        method: 'POST',
        json: { item_ids: itemIds, tag_id: Number(tagId), action: 'add' },
      });
    },
    loadTags() {
      return request('/api/v1/tags/');
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
    loadActivity: local,
    loadRecommendations: local,
    searchMedia: local,
    create: local,
    update: local,
    remove: local,
    updateVisibility: local,
    setMembers: local,
    loadSmartRules: local,
    loadSmartOptions: local,
    saveSmartRules: local,
    syncSmartList: local,
    loadImportStatus: local,
    importCsv: local,
    importMdblist: local,
    importTrakt: local,
    exportList: local,
    addItem: local,
    removeItem: local,
    rateItem: local,
    recommend: local,
    decideRecommendation: local,
    reorderItem: local,
    loadTiers: local,
    moveTierItem: local,
    saveTiers: local,
    fillFromRatings: local,
    undoTierFill: local,
    bulkStatus: local,
    bulkCollection: local,
    bulkList: local,
    bulkTag: local,
    loadTags: local,
  };
}
