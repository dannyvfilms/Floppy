// Pure collection model, field catalog and write mapping shared by the native
// collection screen and its tests. All server access stays in the transport
// adapter.

export const COLLECTION_PAGE_SIZE = 100;
const COLLECTION_PATH = '/api/v1/collection/';

export const ADD_COPY_UNAVAILABLE = 'This item cannot be given another copy from the collection. Open its title page instead.';

// The copy form fields, labels and choices the web renders from the server's
// COLLECTION_FIELD_CONFIG (src/app/config.py). No JSON endpoint publishes the
// catalog, so the client mirrors the same values, including the empty
// "Select" choice the Django form prepends.
function selectField(name, api, label, choices) {
  return {
    name,
    api,
    label,
    type: 'select',
    options: [{ value: '', label: 'Select' }, ...choices.map(value => ({ value, label: value }))],
  };
}

const PURCHASE_PRICE = { name: 'purchasePrice', api: 'purchase_price', label: 'Purchase Price', type: 'number' };
const PURCHASE_LOCATION = { name: 'purchaseLocation', api: 'purchase_location', label: 'Location', type: 'text' };
const COLLECTED_AT = { name: 'collectedAt', api: 'collected_at', label: 'Collected At', type: 'text', help: 'YYYY-MM-DD' };

const VIDEO_FIELDS = [
  selectField('format', 'media_type', 'Format', ['4K Blu-ray', 'Blu-ray', 'DVD', 'Digital', 'Streaming', 'VHS']),
  selectField('resolution', 'resolution', 'Resolution', ['480p', '720p', '1080p', '4K', '8K']),
  selectField('hdr', 'hdr', 'Hdr', ['HDR10', 'HDR10+', 'Dolby Vision', 'HLG']),
  { name: 'is3d', api: 'is_3d', label: '3D', type: 'checkbox' },
  selectField('audioCodec', 'audio_codec', 'Audio codec', ['Dolby Atmos', 'Dolby TrueHD', 'Dolby Digital Plus', 'Dolby Digital', 'DTS:X', 'DTS-HD MA', 'DTS', 'AAC', 'FLAC', 'PCM']),
  selectField('audioChannels', 'audio_channels', 'Audio channels', ['Mono', 'Stereo', '5.1', '7.1', '7.1.2', '7.1.4']),
  selectField('bitrate', 'bitrate', 'Bitrate', ['128', '192', '256', '320', '1411', '4500', '8000']),
  PURCHASE_PRICE,
  PURCHASE_LOCATION,
  COLLECTED_AT,
];

const MUSIC_FIELDS = [
  selectField('format', 'media_type', 'Format', ['Vinyl', 'CD', 'Digital', 'Cassette', 'SACD', 'Streaming']),
  selectField('audioCodec', 'audio_codec', 'Audio codec', ['FLAC', 'MP3', 'AAC', 'ALAC', 'WAV', 'OGG', 'Opus']),
  selectField('audioChannels', 'audio_channels', 'Audio channels', ['Mono', 'Stereo', '5.1', '7.1']),
  selectField('bitrate', 'bitrate', 'Bitrate', ['128', '192', '256', '320', '1411']),
  PURCHASE_PRICE,
  PURCHASE_LOCATION,
  COLLECTED_AT,
];

const BOOKS_FIELDS = [
  selectField('format', 'media_type', 'Format', ['Hardcover', 'Paperback', 'Trade Paperback', 'Digital', 'Audiobook']),
  PURCHASE_PRICE,
  PURCHASE_LOCATION,
  COLLECTED_AT,
];

const GAMES_FIELDS = [
  selectField('resolution', 'resolution', 'Platform', ['PC (Windows)', 'Mac', 'Linux', 'Steam Deck', 'PlayStation 5', 'PlayStation 4', 'Xbox Series X|S', 'Xbox One', 'Nintendo Switch', 'Nintendo Switch 2', 'Mobile (iOS)', 'Mobile (Android)']),
  selectField('format', 'media_type', 'Format', ['Physical', 'Digital', 'ROM', 'Subscription', 'Cloud']),
  selectField('hdr', 'hdr', 'Edition', ['Standard', 'Deluxe', 'Gold', 'Ultimate', "Collector's", 'Game of the Year', 'Complete', 'Definitive', 'Remastered']),
  PURCHASE_PRICE,
  PURCHASE_LOCATION,
  COLLECTED_AT,
];

const BOARDGAME_FIELDS = [
  selectField('format', 'media_type', 'Format', ['Physical', 'Print & Play', 'Digital']),
  PURCHASE_PRICE,
  PURCHASE_LOCATION,
  COLLECTED_AT,
];

// Mirrors COLLECTION_FIELD_BY_TYPE; the video catalog is the fallback the
// server also uses for unlisted media types.
export function copyFieldsFor(mediaType) {
  if (mediaType === 'book' || mediaType === 'manga' || mediaType === 'comic' || mediaType === 'comic_issue') return BOOKS_FIELDS;
  if (mediaType === 'game') return GAMES_FIELDS;
  if (mediaType === 'boardgame') return BOARDGAME_FIELDS;
  if (mediaType === 'music') return MUSIC_FIELDS;
  return VIDEO_FIELDS;
}

export function emptyCopyValues(fields) {
  const values = {};
  (fields || []).forEach(field => {
    values[field.name] = field.type === 'checkbox' ? false : '';
  });
  return values;
}

export function copyValuesFromCopy(copy) {
  return {
    format: copy?.mediaType || '',
    resolution: copy?.resolution || '',
    hdr: copy?.hdr || '',
    is3d: Boolean(copy?.is3d),
    audioCodec: copy?.audioCodec || '',
    audioChannels: copy?.audioChannels || '',
    bitrate: copy?.bitrate == null ? '' : String(copy.bitrate),
    purchasePrice: copy?.purchasePrice || '',
    purchaseLocation: copy?.purchaseLocation || '',
    collectedAt: copy?.collectedAt || '',
  };
}

// GET /api/v1/collection/ pages with limit and offset; the server orders by
// -collected_at itself. Filtering and sorting run over the loaded copies.
export function collectionQuery({ limit = COLLECTION_PAGE_SIZE, offset = 0 } = {}) {
  return { limit, offset };
}

export function totalFromPayload(payload) {
  const total = Number(payload?.pagination?.total);
  return Number.isFinite(total) ? total : null;
}

export function hasMoreFromPayload(payload) {
  return Boolean(payload?.pagination?.next);
}

// The server's per-type chip colors (the web page's own), or {} when absent.
export function mediaTypeColorsFromPayload(payload) {
  const colors = payload?.media_type_colors;
  return colors && typeof colors === 'object' ? colors : {};
}

export function collectionEntriesFromPayload(payload) {
  const entries = Array.isArray(payload) ? payload : payload?.results || [];
  return entries.filter(Boolean);
}

function dateValue(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
}

function completenessFrom(value) {
  if (!value || !value.total) return null;
  return {
    collected: Number(value.collected) || 0,
    total: Number(value.total) || 0,
    isPartial: Boolean(value.is_partial),
  };
}

function itemKey(entry) {
  const item = entry.item || {};
  return `${item.media_type}-${item.source}-${item.media_id}`;
}

// The write route for one more copy of an item, from the raw GET item payload.
// The collection response carries no numeric item id (the item serializer
// excludes it), so POST /api/v1/collection/ cannot be addressed from the
// browser; copies are added through the provider-addressed PUT routes
// (api_media_collection / api_media_episode_collection) instead. Shows are
// collected per episode, so tv and anime buckets are only reachable at
// episode granularity, and season, comic issue, music, podcast and video
// items have no addressed route at all.
const ADDRESSED_MEDIA_TYPES = new Set(['movie', 'book', 'manga', 'comic', 'game', 'boardgame']);

export function collectionAddressFor(item) {
  if (!item || item.source == null || item.media_id == null) return null;
  const query = item.library_media_type ? { library_media_type: String(item.library_media_type) } : undefined;
  if (item.media_type === 'episode' && item.season_number != null && item.episode_number != null) {
    return {
      path: `/api/v1/media/tv/${encodeURIComponent(String(item.source))}`
        + `/${encodeURIComponent(String(item.media_id))}`
        + `/${item.season_number}/episodes/${item.episode_number}/collection/`,
      query,
    };
  }
  if (ADDRESSED_MEDIA_TYPES.has(item.media_type)) {
    return {
      path: `/api/v1/media/${encodeURIComponent(String(item.media_type))}`
        + `/${encodeURIComponent(String(item.source))}`
        + `/${encodeURIComponent(String(item.media_id))}/collection/`,
      query,
    };
  }
  return null;
}

const FORM_TO_API = {
  format: 'media_type',
  resolution: 'resolution',
  hdr: 'hdr',
  is3d: 'is_3d',
  audioCodec: 'audio_codec',
  audioChannels: 'audio_channels',
  bitrate: 'bitrate',
  purchasePrice: 'purchase_price',
  purchaseLocation: 'purchase_location',
  collectedAt: 'collected_at',
};

function apiValue(api, value) {
  if (api === 'bitrate') {
    if (value === '' || value == null) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (api === 'purchase_price') {
    if (value === '' || value == null) return null;
    return String(value);
  }
  if (api === 'is_3d') return Boolean(value);
  return value == null ? '' : String(value);
}

function valueChanged(next, before) {
  return String(next ?? '') !== String(before ?? '');
}

// Build a POST/PATCH body for /api/v1/collection/ from the form values. With
// an `initial` snapshot only the changed keys are sent, so a save never
// rewrites a field the person did not touch.
export function entryPayload(values, initial = null) {
  const payload = {};
  Object.entries(FORM_TO_API).forEach(([formKey, apiKey]) => {
    if (!(formKey in values)) return;
    if (initial && !valueChanged(values[formKey], initial?.[formKey])) return;
    payload[apiKey] = apiValue(apiKey, values[formKey]);
  });
  return payload;
}

// Custom field values changed since `initial`, keyed by field id. null clears
// a text-like value; the server keeps every key this leaves out.
export function customValuesPayload(values = {}, initial = {}) {
  const changed = {};
  Object.keys(values).forEach(key => {
    if (valueChanged(values[key], initial?.[key])) {
      changed[key] = values[key] === '' ? null : values[key];
    }
  });
  Object.keys(initial || {}).forEach(key => {
    if (!(key in values) && initial[key] !== '' && initial[key] != null) changed[key] = null;
  });
  return changed;
}

// The custom-field groups that apply to one media type, in server order.
export function customFieldGroupsFromPayload(payload, mediaType = '') {
  const groups = Array.isArray(payload?.groups) ? payload.groups : [];
  return groups
    .map(group => ({
      id: group.id,
      name: group.name || '',
      fields: (group.fields || [])
        .filter(field => !mediaType || (field.media_types || []).includes(mediaType))
        .map(field => ({
          id: field.id,
          label: field.label || '',
          fieldType: field.field_type || 'text',
          options: Array.isArray(field.options) ? field.options : [],
          mediaTypes: Array.isArray(field.media_types) ? field.media_types : [],
        })),
    }))
    .filter(group => group.fields.length);
}

// Every group, empty ones included, as the field manager edits them.
export function managerGroupsFromPayload(payload) {
  let counter = 0;
  const next = () => { counter += 1; return counter; };
  return (Array.isArray(payload?.groups) ? payload.groups : []).map(group => ({
    clientId: `group-${next()}`,
    id: group.id,
    name: group.name || '',
    fields: (group.fields || []).map(field => ({
      clientId: `field-${next()}`,
      id: field.id,
      label: field.label || '',
      fieldType: field.field_type || 'text',
      options: Array.isArray(field.options) ? field.options : [],
      optionsText: (field.options || []).join('\n'),
      mediaTypes: [...(field.media_types || [])],
    })),
  }));
}

// The PUT body for the whole schema; the server creates, updates and deletes.
export function fieldSchemaBody(groups) {
  return {
    groups: (groups || []).map(group => ({
      id: group.id ?? null,
      name: String(group.name || '').trim(),
      fields: (group.fields || []).map(field => ({
        id: field.id ?? null,
        label: String(field.label || '').trim(),
        field_type: field.fieldType || 'text',
        media_types: [...(field.mediaTypes || [])],
        options: (field.fieldType || 'text') === 'select'
          ? String(field.optionsText ?? (field.options || []).join('\n'))
            .split('\n').map(option => option.trim()).filter(Boolean)
          : [],
      })),
    })),
  };
}

// The one custom filter the shared browser can show: the first dropdown or
// checkbox field, as {id, label, choices}. Text, number and date fields have
// no short value list, as on the web.
export function customFilterFromGroups(groups) {
  for (const group of groups || []) {
    for (const field of group.fields) {
      if (field.fieldType === 'select' && field.options.length) {
        return { id: String(field.id), label: field.label, choices: field.options.map(value => ({ value, label: value })) };
      }
      if (field.fieldType === 'checkbox') {
        return { id: String(field.id), label: field.label, choices: [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }] };
      }
    }
  }
  return null;
}

// The provider-addressed PUT accepts the A/V subset only (no purchase fields)
// and parses collected_at through parse_datetime, so the date needs a time.
const ADDRESSED_API_FIELDS = new Set(['media_type', 'resolution', 'hdr', 'is_3d', 'audio_codec', 'audio_channels', 'bitrate', 'collected_at']);

export function addressedEntryPayload(values) {
  const full = entryPayload(values);
  const payload = {};
  Object.entries(full).forEach(([apiKey, value]) => {
    if (!ADDRESSED_API_FIELDS.has(apiKey)) return;
    // The PUT view keeps stored values for empty strings, so they are not sent.
    if (value === '') return;
    payload[apiKey] = apiKey === 'collected_at' && value && !value.includes('T')
      ? `${value}T00:00:00`
      : value;
  });
  return payload;
}

// Group a (possibly multi-page) list of serialized entries into one browser
// item per underlying media item, newest entry first.
export function collectionItemsFromPayload(payload) {
  const entries = collectionEntriesFromPayload(payload);
  const grouped = new Map();
  entries.forEach(entry => {
    const key = itemKey(entry);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(entry);
  });
  return [...grouped.entries()].map(([key, copies]) => {
    const first = copies[0];
    const item = first.item || {};
    const mediaType = item.library_media_type || item.media_type || '';
    return {
      id: String(first.id),
      mediaType,
      title: item.title || '',
      identity: {
        mediaType,
        source: item.source,
        mediaId: item.media_id,
      },
      image: { src: item.image || null, fallback: '' },
      format: first.media_type || '',
      resolution: first.resolution || '',
      hdr: first.hdr || '',
      location: first.purchase_location || '',
      rating: first.score == null ? null : Number(first.score),
      collectedAt: dateValue(first.collected_at),
      releaseDate: dateValue(item.release_datetime),
      lastWatched: '',
      copyLabel: '',
      customValues: first.custom_field_values || {},
      completeness: completenessFrom(first.completeness),
      address: collectionAddressFor(item),
      copies: copies.map(copy => ({
        id: String(copy.id),
        label: copy.media_type || 'Copy',
        mediaType: copy.media_type || '',
        resolution: copy.resolution || '',
        hdr: copy.hdr || '',
        audioCodec: copy.audio_codec || '',
        audioChannels: copy.audio_channels || '',
        bitrate: copy.bitrate == null ? '' : String(copy.bitrate),
        is3d: Boolean(copy.is_3d),
        purchasePrice: copy.purchase_price == null ? '' : String(copy.purchase_price),
        purchaseLocation: copy.purchase_location || '',
        collectedAt: dateValue(copy.collected_at),
        customValues: copy.custom_field_values || {},
        completeness: completenessFrom(copy.completeness),
      })),
      card: first.card || null,
      entryKey: key,
    };
  });
}

export function createRemoteCollectionActions(request) {
  return {
    mode: 'server',
    load({ limit = COLLECTION_PAGE_SIZE, offset = 0 } = {}) {
      return request(COLLECTION_PATH, { query: collectionQuery({ limit, offset }) });
    },
    // Add one more copy through the provider-addressed PUT. Idempotent on the
    // server: a copy of the same format is reused and updated instead of
    // duplicated.
    addCopy({ address, values }) {
      if (!address) return Promise.reject(new Error(ADD_COPY_UNAVAILABLE));
      return request(address.path, {
        method: 'PUT',
        query: address.query,
        body: addressedEntryPayload(values),
      });
    },
    loadFields() {
      return request(`${COLLECTION_PATH}fields/`);
    },
    saveFields(groups) {
      return request(`${COLLECTION_PATH}fields/`, { method: 'PUT', body: fieldSchemaBody(groups) });
    },
    updateCopy({ entryId, values, initial, customValues, initialCustomValues }) {
      const body = entryPayload(values, initial);
      const custom = customValuesPayload(customValues, initialCustomValues);
      if (Object.keys(custom).length) body.custom_field_values = custom;
      if (!Object.keys(body).length) return Promise.resolve({ unchanged: true });
      return request(`${COLLECTION_PATH}${encodeURIComponent(entryId)}/`, {
        method: 'PATCH',
        body,
      });
    },
    updateSeason({ seasonId, values, initial }) {
      const body = entryPayload(values, initial);
      if (!Object.keys(body).length) return Promise.resolve({ unchanged: true });
      return request(`${COLLECTION_PATH}seasons/${encodeURIComponent(seasonId)}/`, { method: 'PATCH', body });
    },
    removeSeason({ seasonId }) {
      return request(`${COLLECTION_PATH}seasons/${encodeURIComponent(seasonId)}/`, { method: 'DELETE' });
    },
    removeCopy({ entryId }) {
      return request(`${COLLECTION_PATH}${encodeURIComponent(entryId)}/`, {
        method: 'DELETE',
      });
    },
  };
}

export function createLocalCollectionActions(reason) {
  const local = async () => ({ local: true, reason });
  const unavailable = async () => {
    throw new Error('Sign in to your Floppy server to change your collection.');
  };
  return {
    mode: 'local',
    reason,
    load: local,
    loadFields: local,
    saveFields: unavailable,
    addCopy: unavailable,
    updateCopy: unavailable,
    removeCopy: unavailable,
    updateSeason: unavailable,
    removeSeason: unavailable,
  };
}
