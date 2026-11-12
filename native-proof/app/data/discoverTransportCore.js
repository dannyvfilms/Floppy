import { expectObject } from './payloadGuard.js';

// Shown only until the server's chips arrive with the first payload.
const DEFAULT_MEDIA_OPTIONS = [
  { value: 'all', label: 'All Media' },
  { value: 'hidden', label: 'Hidden' },
];

function yearOf(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getUTCFullYear();
}

function tastePercent(item) {
  const score = item.display_score ?? item.final_score;
  if (score == null) return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return Math.round((value <= 1 ? value * 100 : value));
}

function line(parts) {
  return { join: 'dot', parts };
}

function discoverActions() {
  return {
    href: '',
    clickable: true,
    items: [
      { kind: 'post', action: 'planning', tone: 'indigo', title: 'Add to Planning', glyph: '＋' },
      { kind: 'post', action: 'dismiss', tone: 'rose', title: 'Hide from Discover', glyph: '⦸' },
      { kind: 'post', action: 'lists', tone: 'emerald', title: 'Add to custom lists', glyph: '☰' },
    ],
  };
}

export function cardFromDiscoverItem(item, rowKey, matchLabel = '') {
  const mediaType = item.media_type || 'movie';
  const year = yearOf(item.release_date);
  const taste = tastePercent(item);
  const meta = [];
  if (year) meta.push(String(year));
  if (taste != null && matchLabel) meta.push(`${taste}% ${matchLabel}`);
  const cardKey = `${mediaType}-${item.source}-${item.media_id}`;
  return {
    mediaType,
    identity: {
      mediaType,
      source: item.source,
      mediaId: String(item.media_id),
      title: item.title,
      image: item.image || null,
    },
    shape: mediaType === 'music' || mediaType === 'podcast' ? 'square' : 'poster',
    image: { src: item.image || null, fallback: '', source: 'primary' },
    title: item.title || '',
    altTitle: item.localized_title && item.localized_title !== item.title
      ? item.localized_title
      : (item.original_title && item.original_title !== item.title ? item.original_title : null),
    statusChip: null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: meta.length ? [line(meta.map((text, index) => ({ text, muted: index > 0 })))] : [],
    actions: discoverActions(),
    cardKey,
    rowKey,
    // The provider score is not the viewer's rating; the web card shows none.
    rating: null,
    ratingEditable: false,
    csrfToken: '',
  };
}

export function discoverRowsFromPayload(payload) {
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  return rows
    .map((row, index) => {
      const first = (row.items || [])[0];
      return {
        // The All tab repeats a row key once per media type, so key by type too.
        key: `${row.key}:${first?.media_type || index}`,
        title: row.title || row.key,
        why: row.why || '',
        matchSignal: row.match_signal || null,
        isStale: !!row.is_stale,
        items: (row.items || []).map(item => cardFromDiscoverItem(item, row.key, row.match_label || '')),
      };
    })
    .filter(row => row.items.length);
}

export function discoverMediaOptionsFromPayload(payload) {
  const options = Array.isArray(payload?.media_options) ? payload.media_options : [];
  return options.length
    ? options.map(option => ({ value: option.value, label: option.label }))
    : DEFAULT_MEDIA_OPTIONS;
}

function hiddenDateLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `Hidden ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
}

export function hiddenFromPayload(payload) {
  const results = Array.isArray(payload?.results) ? payload.results : [];
  return results.map(entry => ({
    mediaType: entry.media_type || 'movie',
    shape: entry.media_type === 'music' || entry.media_type === 'podcast' ? 'square' : 'poster',
    image: { src: entry.image || null, fallback: '', source: 'primary' },
    title: entry.title || '',
    altTitle: null,
    statusChip: null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: hiddenDateLabel(entry.hidden_at)
      ? [line([{ text: hiddenDateLabel(entry.hidden_at) }])]
      : [],
    actions: {
      href: '',
      clickable: true,
      items: [
        { kind: 'post', action: 'unhide', tone: 'indigo', title: 'Unhide from Discover', glyph: '↺' },
      ],
    },
    cardKey: `hidden-${entry.item_id}`,
    itemId: entry.item_id,
    identity: {
      mediaType: entry.media_type || '',
      source: entry.source || '',
      mediaId: entry.media_id ? String(entry.media_id) : '',
      title: entry.title || '',
    },
    rating: null,
    ratingEditable: false,
    csrfToken: '',
  }));
}

export function createRemoteDiscoverActions(request) {
  return {
    mode: 'server',
    loadRows({ mediaType = 'all', showMore = false } = {}) {
      const query = { show_more: showMore ? 1 : 0 };
      if (mediaType && mediaType !== 'all' && mediaType !== 'hidden') {
        query.media_type = mediaType;
      }
      return request('/api/v1/discover/', { query }).then(data => expectObject(data, 'Discover'));
    },
    loadHidden() {
      return request('/api/v1/discover/hidden/').then(data => expectObject(data, 'Discover'));
    },
    loadStatus({ mediaType = 'all', showMore = false } = {}) {
      const query = { show_more: showMore ? 1 : 0 };
      if (mediaType && mediaType !== 'all' && mediaType !== 'hidden') {
        query.media_type = mediaType;
      }
      return request('/api/v1/discover/status/', { query }).then(data => expectObject(data, 'Discover'));
    },
    refresh({ mediaType = 'all', showMore = false } = {}) {
      const body = { show_more: Boolean(showMore) };
      if (mediaType && mediaType !== 'all' && mediaType !== 'hidden') {
        body.media_type = mediaType;
      }
      return request('/api/v1/discover/refresh/', { method: 'POST', body });
    },
    plan({ mediaType, source, mediaId, title, image }) {
      return request(`/api/v1/media/${encodeURIComponent(mediaType)}/`, {
        method: 'POST',
        body: {
          source,
          media_id: String(mediaId),
          status: 'Planning',
          title,
          image: image || '',
        },
      });
    },
    unplan({ mediaType, source, mediaId }) {
      return request(
        `/api/v1/media/${encodeURIComponent(mediaType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}/`,
        { method: 'DELETE' },
      );
    },
    hide({ itemId, identity, title, image }) {
      const body = { action: 'hide' };
      if (itemId) {
        body.item_id = itemId;
      } else if (identity?.mediaId) {
        body.source = identity.source;
        body.media_type = identity.mediaType;
        body.media_id = identity.mediaId;
        if (identity.seasonNumber != null) body.season_number = identity.seasonNumber;
        if (title) body.title = title;
        if (image) body.image = image;
      }
      return request('/api/v1/discover/hidden/', { method: 'POST', body });
    },
    unhide({ itemId }) {
      return request('/api/v1/discover/hidden/', {
        method: 'POST',
        body: { action: 'unhide', item_id: itemId },
      });
    },
  };
}

export function createLocalDiscoverActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    loadRows: local,
    loadHidden: local,
    loadStatus: local,
    refresh: local,
    plan: local,
    unplan: local,
    hide: local,
    unhide: local,
  };
}

export { DEFAULT_MEDIA_OPTIONS };