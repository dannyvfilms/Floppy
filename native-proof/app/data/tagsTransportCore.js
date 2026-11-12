const TAGS_PATH = '/api/v1/tags/';

// GET /api/v1/tags/ returns id/name/created_at/item_count plus the
// type_breakdown the web Tags page shows ({media_type, count} per type).
function typeLabel(mediaType) {
  const value = String(mediaType || '');
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function typesFromPayload(breakdown) {
  if (!Array.isArray(breakdown)) return [];
  return breakdown
    .filter(entry => entry && entry.media_type)
    .map(entry => ({
      key: String(entry.media_type),
      label: typeLabel(entry.media_type),
      count: Number(entry.count) || 0,
    }));
}

export function tagFromPayload(payload) {
  if (!payload || payload.id === undefined || payload.id === null) return null;
  const count = Number(payload.item_count);
  return {
    id: payload.id,
    name: String(payload.name || ''),
    count: Number.isFinite(count) ? count : 0,
    createdAt: payload.created_at || '',
    types: typesFromPayload(payload.type_breakdown),
  };
}

export function tagsFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results;
  if (!Array.isArray(results)) return [];
  return results.map(tagFromPayload).filter(Boolean);
}

export function sortTags(tags, sort = 'name') {
  return [...tags].sort((left, right) => (sort === 'count'
    ? right.count - left.count || left.name.localeCompare(right.name)
    : left.name.localeCompare(right.name)));
}

export function createRemoteTagsActions(request) {
  return {
    mode: 'server',
    load() {
      return request(TAGS_PATH);
    },
    remove({ tagId }) {
      return request(`/api/v1/tags/${encodeURIComponent(tagId)}/`, { method: 'DELETE' });
    },
  };
}

export function createLocalTagsActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    load: local,
    remove: local,
  };
}
