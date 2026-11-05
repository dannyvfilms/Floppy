import { getActiveAuthSession } from '../data/authSession.js';

const DEFAULT_CONFIG = {
  baseUrl: (typeof process !== 'undefined' && process.env && process.env.EXPO_PUBLIC_FLOPPY_BASE_URL) || '',
  token: (typeof process !== 'undefined' && process.env && process.env.EXPO_PUBLIC_FLOPPY_TOKEN) || '',
  csrfToken: (typeof process !== 'undefined' && process.env && process.env.EXPO_PUBLIC_FLOPPY_CSRF) || '',
  fetchImpl: null,
  auth: null,
};

let config = { ...DEFAULT_CONFIG };

const STATUS_BY_CODE = { 0: 'Planning', 1: 'In progress', 2: 'Paused', 3: 'Completed', 4: 'Dropped' };
const STATUS_OPTIONS = ['Planning', 'In progress', 'Paused', 'Completed', 'Dropped']
  .map(value => ({ value, label: value }));
const PROGRESS_TYPES = new Set(['anime', 'manga', 'book', 'comic', 'game', 'boardgame', 'music']);
const DATE_TYPES = new Set(['movie', 'anime', 'manga', 'book', 'comic', 'game', 'boardgame', 'music']);
const EPISODIC_TYPES = new Set(['tv', 'season', 'episode', 'anime']);

export function configureMediaCardTransport(next = {}) {
  config = { ...config, ...next };
  if (next.fetchImpl === null) config.fetchImpl = null;
  return { ...config };
}

function activeAuth() {
  return config.auth || getActiveAuthSession();
}

export function resetMediaCardTransport() {
  config = { ...DEFAULT_CONFIG };
}

export function hasMediaCardTransport() {
  const auth = activeAuth();
  return Boolean(config.baseUrl || (auth && typeof auth.request === 'function'));
}

export function mediaCardTransportLabel() {
  const auth = activeAuth();
  return config.baseUrl || (auth && auth.serverUrl) || 'demo';
}

function queryString(query = {}) {
  const parts = Object.entries(query)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

export function mediaPath(identity) {
  const { mediaType, source, mediaId, seasonNumber, episodeNumber } = identity || {};
  const pathType = mediaType === 'episode' ? 'tv' : mediaType;
  let path = `/api/v1/media/${encodeURIComponent(pathType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}`;
  if (seasonNumber != null) path += `/${encodeURIComponent(seasonNumber)}`;
  if (episodeNumber != null) path += `/${encodeURIComponent(episodeNumber)}`;
  return path;
}

function episodeActionPath(identity, action) {
  const { source, mediaId, seasonNumber, episodeNumber } = identity || {};
  return `/api/v1/media/tv/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}`
    + `/${encodeURIComponent(seasonNumber)}/episodes/${encodeURIComponent(episodeNumber)}/${action}/`;
}

export function mediaCardVariant(identity) {
  if (!identity) return '';
  if (identity.mediaType === 'episode') return 'episode';
  if (identity.mediaType === 'music') return 'song';
  if (identity.mediaType === 'podcast' && identity.episodeNumber != null) return 'song';
  if (identity.episodeNumber != null) return 'episode';
  return '';
}

async function request(path, { method = 'GET', body, query, form } = {}) {
  const auth = activeAuth();
  if (auth && typeof auth.request === 'function') {
    return auth.request(path, { method, body, query, form });
  }
  const fetcher = config.fetchImpl || fetch;
  const headers = { Accept: 'application/json' };
  let payload;
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  if (form !== undefined) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    const params = new URLSearchParams();
    Object.entries(form).forEach(([key, value]) => {
      if (value !== undefined && value !== null) params.append(key, String(value));
    });
    payload = params.toString();
  }
  if (config.token) headers.Authorization = `Bearer ${config.token}`;
  if (config.csrfToken) headers['X-CSRFToken'] = config.csrfToken;
  const response = await fetcher(`${config.baseUrl}${path}${queryString(query)}`, {
    method,
    headers,
    body: payload,
    credentials: config.token ? 'omit' : 'include',
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && data.detail ? data.detail : `Request failed (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function resultList(payload) {
  if (Array.isArray(payload)) return payload;
  return payload && Array.isArray(payload.results) ? payload.results : [];
}

function dateText(value) {
  if (!value) return '';
  return String(value).slice(0, 10);
}

function statusLabel(value) {
  if (typeof value === 'number') return STATUS_BY_CODE[value] || '';
  return value || '';
}

function currentConsumption(state) {
  const consumptions = resultList(state && state.consumptions);
  return consumptions[0] || null;
}

function field(name, label, type, value, extra = {}) {
  return { name, label, type, value: value == null ? '' : String(value), ...extra };
}

function trackFields(identity, detail, consumption) {
  const mediaType = identity.mediaType;
  const fields = [
    {
      name: 'status',
      label: 'Status',
      type: 'select',
      value: statusLabel(consumption && consumption.status) || 'Planning',
      required: true,
      options: STATUS_OPTIONS,
    },
    field('score', 'Score', 'number', consumption && consumption.score, { min: 0, max: 10 }),
  ];
  if (PROGRESS_TYPES.has(mediaType)) {
    fields.push(field('progress', 'Progress', 'number', consumption && consumption.progress, {
      min: 0,
      max: detail && detail.max_progress ? detail.max_progress : null,
      help: detail && detail.progress_unit ? String(detail.progress_unit) : '',
    }));
  }
  if (DATE_TYPES.has(mediaType)) {
    fields.push(field('start_date', 'Start date', 'date', dateText(consumption && consumption.start_date)));
    fields.push(field('end_date', 'End date', 'date', dateText(consumption && consumption.end_date)));
  }
  return fields;
}

function metadataFields(detail) {
  if (!detail) return [];
  const rows = [
    ['Title', detail.title],
    ['Media type', detail.media_type || (detail.media_metadata && detail.media_metadata.media_type)],
    ['Provider', detail.source || (detail.media_metadata && detail.media_metadata.source)],
    ['Provider id', detail.media_id],
    ['Release', detail.media_metadata && detail.media_metadata.release_date],
    ['Genres', Array.isArray(detail.genres) ? detail.genres.join(', ') : detail.genres],
    ['Provider score', detail.score == null ? '' : String(detail.score)],
  ];
  return rows
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([label, value]) => ({ label, value: String(value) }));
}

function collectionRows(entries, identity) {
  return resultList(entries)
    .filter(entry => {
      const item = (entry && entry.item) || {};
      return String(item.media_id) === String(identity.mediaId) && (!item.source || item.source === identity.source);
    })
    .map(entry => ({
      id: String(entry.id),
      title: (entry.item && entry.item.title) || 'Owned copy',
      detail: [entry.media_type, entry.resolution, entry.hdr, entry.is_3d ? '3D' : '']
        .filter(Boolean)
        .join(' · '),
      date: dateText(entry.collected_at),
    }));
}

function playRows(history) {
  return resultList(history).map(entry => {
    const status = statusLabel(entry.status);
    return {
      id: String(entry.consumption_id || entry.id || entry.created || Math.random()),
      title: status || 'Play',
      detail: entry.progress != null ? `Progress ${entry.progress}` : '',
      date: dateText(entry.end_date || entry.progressed_at || entry.created || entry.start_date),
    };
  });
}

function statusChanges(history) {
  return resultList(history)
    .flatMap(entry => (entry.changes || []).map(change => ({ ...change, timestamp: entry.timestamp })))
    .filter(change => change.field === 'status')
    .map((change, index) => ({
      id: String(change.timestamp || index),
      old: statusLabel(change.old_value),
      next: statusLabel(change.new_value) || 'No Status',
      reason: change.reason || change.entry_source || '',
      date: dateText(change.timestamp),
    }));
}

function errorTab(tab, error) {
  return { ...tab, status: 'error', error: (error && error.message) || 'Request failed' };
}

function readyTab(tab, payload) {
  return { ...tab, status: 'ready', error: '', ...payload };
}

async function safeTab(tab, loader) {
  try {
    return readyTab(tab, await loader());
  } catch (error) {
    return errorTab(tab, error);
  }
}

async function loadTagTab(identity) {
  const [all, applied] = await Promise.all([
    request('/api/v1/tags/', { query: { limit: 200 } }),
    request(`${mediaPath(identity)}/tags/`),
  ]);
  const appliedIds = new Set(resultList(applied).map(tag => String(tag.id)));
  return {
    tags: resultList(all).map(tag => ({
      id: String(tag.id),
      name: tag.name,
      hasTag: appliedIds.has(String(tag.id)),
      pending: false,
      error: '',
    })),
  };
}

async function loadMetadataTab(identity) {
  const detail = await request(`${mediaPath(identity)}/`);
  return {
    fields: metadataFields(detail),
    imageUrl: detail.image || '',
    itemId: detail.id || null,
    canEditArtwork: Boolean(detail.tracked && detail.id),
  };
}

async function loadCollectionTab(identity) {
  const entries = await request('/api/v1/collection/', {
    query: { item_media_type: identity.mediaType, limit: 200 },
  });
  return { entries: collectionRows(entries, identity) };
}

async function loadPlaysTab(identity) {
  const history = await request(`${mediaPath(identity)}/history/`, { query: { limit: 50 } });
  return { entries: playRows(history) };
}

async function loadStatusHistoryTab(identity) {
  const history = await request(`${mediaPath(identity)}/changes_history/`, { query: { limit: 50 } });
  return { changes: statusChanges(history) };
}

async function loadDiscoverTab(identity, detail) {
  const hidden = await request('/api/v1/discover/hidden/');
  const itemId = detail && detail.id ? String(detail.id) : '';
  const entry = resultList(hidden).find(item => String(item.item_id) === itemId);
  return { hidden: Boolean(entry), itemId: itemId || null, canToggle: Boolean(itemId) };
}

function todayText() {
  return new Date().toISOString().slice(0, 10);
}

function variantFields(identity, consumption) {
  const podcast = identity.mediaType === 'podcast';
  return [field(
    'end_date',
    mediaCardVariant(identity) === 'episode' ? 'Watch date' : (podcast ? 'Play date' : 'Listen date'),
    'date',
    dateText(consumption && consumption.end_date) || todayText(),
  )];
}

function variantModel(identity, detail, consumption) {
  const variant = mediaCardVariant(identity);
  const podcast = identity.mediaType === 'podcast';
  return {
    mediaType: identity.mediaType,
    variant,
    title: (detail && detail.title) || identity.title || '',
    subtitle: identity.subtitle || '',
    action: variant === 'episode' ? episodeActionPath(identity, 'watch') : '',
    deleteAction: variant === 'episode' ? episodeActionPath(identity, 'drop') : '',
    fields: variantFields(identity, consumption),
    notes: null,
    submitLabel: variant === 'episode' ? 'Add watch' : (podcast ? 'Add play' : 'Add listen'),
    deleteLabel: variant === 'episode' ? 'Drop' : 'Delete',
    trackTime: false,
  };
}

function needsVariant(identity) {
  return mediaCardVariant(identity) !== '';
}

export async function loadTrack(identity) {
  if (needsVariant(identity)) {
    if (mediaCardVariant(identity) === 'episode') {
      const state = await request(`${mediaPath(identity)}/state/`);
      const consumption = currentConsumption(state);
      return {
        tracked: Boolean(state.tracked),
        title: (state.media && state.media.title) || identity.title || '',
        model: variantModel(identity, state.media, consumption),
        tabs: [],
      };
    }
    return {
      tracked: false,
      title: identity.title || '',
      model: variantModel(identity, null, null),
      tabs: [],
    };
  }
  const state = await request(`${mediaPath(identity)}/state/`);
  let detail = null;
  try { detail = await request(`${mediaPath(identity)}/`); } catch { detail = null; }
  const consumption = currentConsumption(state);
  const episodic = EPISODIC_TYPES.has(identity.mediaType);
  const tabs = [
    { id: 'tags', label: 'Tags', kind: 'tags', status: 'loading', error: '' },
    { id: 'metadata', label: 'Metadata', kind: 'metadata', status: 'loading', error: '' },
    { id: 'collection', label: 'Collection', kind: 'collection', status: 'loading', error: '' },
    { id: 'plays', label: episodic ? 'Episode plays' : 'Plays', kind: 'plays', status: 'loading', error: '' },
    { id: 'status-history', label: 'Status history', kind: 'status-history', status: 'loading', error: '' },
    { id: 'discover', label: 'Discover', kind: 'discover', status: 'loading', error: '' },
  ];
  const loaded = await Promise.all([
    safeTab(tabs[0], () => loadTagTab(identity)),
    safeTab(tabs[1], () => loadMetadataTab(identity)),
    safeTab(tabs[2], () => loadCollectionTab(identity)),
    safeTab(tabs[3], () => loadPlaysTab(identity)),
    safeTab(tabs[4], () => loadStatusHistoryTab(identity)),
    safeTab(tabs[5], () => loadDiscoverTab(identity, detail)),
  ]);
  const title = (detail && detail.title) || (state.media && state.media.title) || identity.title || '';
  return {
    tracked: Boolean(state.tracked),
    title,
    model: {
      mediaType: identity.mediaType,
      title,
      subtitle: identity.subtitle || '',
      action: `${mediaPath(identity)}/`,
      deleteAction: state.tracked ? `${mediaPath(identity)}/` : '',
      csrfToken: config.csrfToken,
      fields: trackFields(identity, detail, consumption),
      notes: { value: (consumption && consumption.notes) || '', label: 'Notes' },
      submitLabel: state.tracked ? 'Update' : 'Add',
      deleteLabel: 'Delete',
      trackTime: false,
    },
    tabs: loaded,
  };
}

export async function loadTrackTabs(identity) {
  const detail = await request(`${mediaPath(identity)}/`).catch(() => null);
  const tabs = [
    { id: 'tags', label: 'Tags', kind: 'tags', status: 'loading', error: '' },
    { id: 'metadata', label: 'Metadata', kind: 'metadata', status: 'loading', error: '' },
    { id: 'collection', label: 'Collection', kind: 'collection', status: 'loading', error: '' },
    { id: 'plays', label: EPISODIC_TYPES.has(identity.mediaType) ? 'Episode plays' : 'Plays', kind: 'plays', status: 'loading', error: '' },
    { id: 'status-history', label: 'Status history', kind: 'status-history', status: 'loading', error: '' },
    { id: 'discover', label: 'Discover', kind: 'discover', status: 'loading', error: '' },
  ];
  return Promise.all([
    safeTab(tabs[0], () => loadTagTab(identity)),
    safeTab(tabs[1], () => loadMetadataTab(identity)),
    safeTab(tabs[2], () => loadCollectionTab(identity)),
    safeTab(tabs[3], () => loadPlaysTab(identity)),
    safeTab(tabs[4], () => loadStatusHistoryTab(identity)),
    safeTab(tabs[5], () => loadDiscoverTab(identity, detail)),
  ]);
}

export async function loadLists(identity, title) {
  const [all, membership] = await Promise.all([
    request('/api/v1/lists/', { query: { limit: 200 } }),
    request(`${mediaPath(identity)}/lists/`, { query: { limit: 200 } }),
  ]);
  const memberIds = new Set(resultList(membership).map(entry => String(entry.list_id)));
  return {
    itemId: identity.itemId || identity.mediaId,
    title: title || identity.title || '',
    lists: resultList(all).map(list => ({
      id: String(list.id),
      name: list.name,
      hasItem: memberIds.has(String(list.id)),
      tags: [],
    })),
    tags: [],
    selectedTag: '',
    toggleUrl: '',
    csrfToken: config.csrfToken,
  };
}

export async function toggleList(identity, listId, hasItem) {
  await request(`${mediaPath(identity)}/lists/${encodeURIComponent(listId)}/`, {
    method: hasItem ? 'DELETE' : 'PUT',
    body: hasItem ? undefined : {},
  });
  return { hasItem: !hasItem };
}

function trackBody(model, values) {
  const body = {};
  for (const fieldDefinition of model.fields || []) {
    const value = values[fieldDefinition.name];
    if (value === undefined) continue;
    if (value === '') {
      body[fieldDefinition.name] = null;
      continue;
    }
    if (fieldDefinition.type === 'number') body[fieldDefinition.name] = Number(value);
    else body[fieldDefinition.name] = value;
  }
  if (values.notes !== undefined) body.notes = values.notes || '';
  return body;
}

export async function saveTrack(identity, model, values, tracked) {
  if (model && model.variant === 'episode') {
    await request(episodeActionPath(identity, 'watch'), {
      method: 'POST',
      body: { end_date: values.end_date || null },
    });
    return { tracked: true };
  }
  if (model && model.variant === 'song') {
    if (identity.mediaType === 'podcast') {
      await request('/api/v1/podcasts/episodes/plays/', {
        method: 'POST',
        body: {
          show_id: identity.showId,
          episode_id: identity.trackId,
          episode_uuid: identity.mediaId,
          end_date: values.end_date || null,
        },
      });
    } else {
      await request('/api/v1/music/songs/plays/', {
        method: 'POST',
        body: {
          album_id: identity.albumId,
          track_id: identity.trackId,
          recording_id: identity.recordingId,
          end_date: values.end_date || null,
        },
      });
    }
    return { tracked: true };
  }
  const body = trackBody(model, values);
  if (tracked) {
    await request(`${mediaPath(identity)}/`, { method: 'PATCH', body });
    return { tracked: true };
  }
  await request(`/api/v1/media/${encodeURIComponent(identity.mediaType)}/`, {
    method: 'POST',
    body: {
      source: identity.source,
      media_id: identity.mediaId,
      ...(identity.seasonNumber != null ? { season_number: identity.seasonNumber } : {}),
      ...body,
    },
  });
  return { tracked: true };
}

export async function deleteTrack(identity, model) {
  if (model && model.variant === 'episode') {
    await request(episodeActionPath(identity, 'drop'), { method: 'POST', body: {} });
    return;
  }
  await request(`${mediaPath(identity)}/`, { method: 'DELETE' });
}

export async function setTags(identity, tagIds) {
  const payload = await request(`${mediaPath(identity)}/tags/`, {
    method: 'PUT',
    body: { tag_ids: tagIds.map(id => Number(id)) },
  });
  return resultList(payload).map(tag => String(tag.id));
}

export async function createTag(name) {
  const tag = await request('/api/v1/tags/', { method: 'POST', body: { name } });
  return { id: String(tag.id), name: tag.name };
}

export async function saveArtwork(identity, imageUrl) {
  await request(`${mediaPath(identity)}/`, { method: 'PATCH', body: { image_url: imageUrl } });
}

export async function saveScore(identity, score) {
  if (mediaCardVariant(identity) === 'episode') {
    await request(episodeActionPath(identity, 'score'), { method: 'PATCH', body: { score } });
    return { score };
  }
  if (identity.mediaType === 'podcast' && identity.showId != null) {
    await request(`/api/v1/podcasts/shows/${encodeURIComponent(identity.showId)}/`, {
      method: 'PATCH',
      body: { score },
    });
    return { score };
  }
  if (identity.mediaType === 'music' && identity.musicId != null) {
    await request(`/api/v1/music/tracks/${encodeURIComponent(identity.musicId)}/score/`, {
      method: 'PATCH',
      body: { score },
    });
    return { score };
  }
  await request(`${mediaPath(identity)}/`, { method: 'PATCH', body: { score } });
  return { score };
}

export async function setDiscoverHidden(itemId, hidden) {
  await request('/api/v1/discover/hidden/', {
    method: 'POST',
    body: { item_id: Number(itemId), action: hidden ? 'hide' : 'unhide' },
  });
  return { hidden };
}

export async function runDiscoverAction(vals) {
  const { action, ...fields } = vals || {};
  if (action !== 'planning' && action !== 'dismiss') {
    throw new Error('Unsupported Discover action.');
  }
  await request('/discover/action', { method: 'POST', form: { ...fields, action } });
  return { action };
}

export async function reorderListItem(ordering, step) {
  const listId = ordering && (ordering.listId || ordering.list_id);
  const itemId = ordering && ordering.itemId;
  if (!listId || itemId == null) {
    throw new Error('This list item cannot be reordered.');
  }
  await request(`/api/v1/lists/${encodeURIComponent(listId)}/items/reorder/`, {
    method: 'POST',
    body: { item_id: Number(itemId), action: step },
  });
  return { itemId, action: step };
}

export async function reorderListItems(ordering, itemIds) {
  const listId = ordering && (ordering.listId || ordering.list_id);
  if (!listId || !Array.isArray(itemIds) || !itemIds.length) {
    throw new Error('This list cannot be reordered.');
  }
  const ids = itemIds.map(itemId => Number(itemId));
  await request(`/api/v1/lists/${encodeURIComponent(listId)}/items/order/`, {
    method: 'PUT',
    body: { item_ids: ids },
  });
  return { itemIds: ids };
}
