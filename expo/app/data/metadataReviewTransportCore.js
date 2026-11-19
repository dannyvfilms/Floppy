const BASE = '/api/v1/metadata-review/';
const array = value => (Array.isArray(value) ? value : []);

export function queueFromPayload(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  return { needsReview: array(data.needs_review), saved: array(data.saved) };
}

export function candidatesFromPayload(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  return {
    source: data.source || null,
    provider: data.provider || '',
    providers: array(data.providers),
    query: data.query || '',
    results: array(data.candidates).map(row => ({
      id: String(row.media_id),
      title: row.title,
      image: row.image || '',
      meta: row.year ? String(row.year) : '',
    })),
  };
}

// Preview rows come keyed by source episode; `mapping` starts from the
// server's suggestion so applying without edits uses the proposed numbering.
export function previewFromPayload(payload) {
  const data = payload && typeof payload === 'object' ? payload : null;
  if (!data || !data.token) return null;
  const mapping = {};
  for (const row of array(data.rows)) if (row.selected) mapping[row.id] = row.selected;
  return {
    token: data.token,
    source: data.source,
    destination: data.destination,
    counts: data.counts || {},
    referenceCount: Number(data.reference_count) || 0,
    rows: array(data.rows),
    episodes: array(data.episodes),
    scalarConflicts: data.scalar_conflicts || {},
    mapping,
  };
}

export function applyBody(preview, { mapping, decisions, note } = {}) {
  return {
    destination_item_id: preview.destination.id,
    token: preview.token,
    mapping: mapping || preview.mapping || {},
    decisions: decisions || {},
    note: note || '',
  };
}

export function unmappedRows(preview, mapping) {
  const chosen = mapping || preview.mapping || {};
  return array(preview.rows).filter(row => !chosen[row.id]);
}

export function createRemoteMetadataReviewActions(request) {
  const send = (method, path, body) => request(path, { method, body: body === undefined ? {} : body });
  const item = (id, suffix) => `${BASE}items/${encodeURIComponent(id)}/${suffix}`;
  return {
    mode: 'server',
    queue: () => request(BASE),
    reference: (referenceId, action) => send('POST', `${BASE}references/${encodeURIComponent(referenceId)}/`, { action }),
    candidates: (itemId, { q, provider } = {}) => request(item(itemId, 'candidates/'), {
      query: Object.fromEntries(Object.entries({ q, provider }).filter(([, value]) => value)),
    }),
    preview: (itemId, { provider, q, destinationMediaId }) => send('POST', item(itemId, 'preview/'), {
      provider, q, destination_media_id: destinationMediaId,
    }),
    apply: (itemId, preview, options) => send('POST', item(itemId, 'apply/'), applyBody(preview, options)),
  };
}

export function createLocalMetadataReviewActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    queue: local,
    reference: local,
    candidates: local,
    preview: local,
    apply: local,
  };
}
