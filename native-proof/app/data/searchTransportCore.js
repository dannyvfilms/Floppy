import { expectObject } from './payloadGuard.js';

// Search endpoints. Library and online results, source pills, suggestions and
// parent pickers all come from the server in the shapes the web page renders.

export function suggestionsFromPayload(payload) {
  const rows = Array.isArray(payload?.suggestions) ? payload.suggestions : [];
  // A null row is skipped, like the other mappers (tagsFromPayload etc.).
  return rows.filter(row => row && typeof row === 'object').map((row, index) => ({
    id: String(row.id ?? index),
    title: row.title || '',
    subtitle: row.subtitle || '',
    image: row.image || null,
    // Saved items carry their web detail URL; Detail resolves it to an identity.
    href: row.url || '',
    url: row.url || '',
  }));
}

export function searchBarFromPayload(payload) {
  return {
    mediaTypes: Array.isArray(payload?.media_types) ? payload.media_types : [],
    barcodeTypes: Array.isArray(payload?.barcode_types) ? payload.barcode_types : [],
    labels: payload?.labels || {},
    sources: Array.isArray(payload?.sources) ? payload.sources : [],
    defaultSource: payload?.default_source || '',
  };
}

export function resultsQuery({ query, mediaType, source, page, layout } = {}) {
  const params = { q: query || '', media_type: mediaType || 'all' };
  if (source) params.source = source;
  if (page && page > 1) params.page = page;
  if (layout) params.layout = layout;
  return params;
}

export function createRemoteSearchActions(request) {
  return {
    mode: 'server',
    loadSources({ mediaType = 'all' } = {}) {
      return request('/api/v1/search/sources/', { query: { media_type: mediaType } }).then(data => expectObject(data, 'Search'));
    },
    loadSuggestions({ query, mediaType = 'all' } = {}) {
      return request('/api/v1/search/suggestions/', { query: { q: query, media_type: mediaType } }).then(data => expectObject(data, 'Search'));
    },
    loadResults(params = {}) {
      return request('/api/v1/search/results/', { query: resultsQuery(params) }).then(data => expectObject(data, 'Search'));
    },
    loadParents({ kind, query } = {}) {
      return request('/api/v1/search/parents/', { query: { kind, q: query } });
    },
    loadManualOptions() {
      return request('/api/v1/search/manual-entry/');
    },
    createManualEntry(data) {
      return request('/api/v1/search/manual-entry/', { method: 'POST', body: data });
    },
    createMusic({ kind, id } = {}) {
      return request('/api/v1/search/music/create/', { method: 'POST', body: { kind, id } });
    },
  };
}

export function createLocalSearchActions(reason) {
  const local = async () => { throw new Error(reason); };
  return {
    mode: 'local',
    reason,
    loadSources: local,
    loadSuggestions: local,
    loadResults: local,
    loadParents: local,
    loadManualOptions: local,
    createManualEntry: local,
    createMusic: local,
  };
}
