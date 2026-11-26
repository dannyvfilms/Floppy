import { useCallback, useEffect, useRef, useState } from 'react';

// Query and loading state for the Anime Seasons page, shared by web and Expo.
// The server builds the page model (app.anime_seasons), so the client only
// turns FilterBar intents and season steps into the next query.

const FIELD_KEYS = { season: 'season', season_year: 'year', format: 'format' };

// Apply one intent to a query ({ year, season, format, sort, direction, statuses }).
// A removed key falls back to the server default (current season, all formats,
// the sort's natural direction), so "clear" never has to know those defaults.
export function applyAnimeSeasonsIntent(query = {}, intent = {}) {
  const next = { ...query };
  if (intent.type === 'clear') return {};
  if (intent.type === 'step') return { ...next, year: intent.year, season: intent.season };
  if (intent.type === 'field' && FIELD_KEYS[intent.key]) {
    next[FIELD_KEYS[intent.key]] = intent.value;
  } else if (intent.type === 'clearField' && FIELD_KEYS[intent.key]) {
    delete next[FIELD_KEYS[intent.key]];
  } else if (intent.type === 'set' && intent.key === 'sort') {
    next.sort = intent.value;
    delete next.direction;
  } else if (intent.type === 'set' && (intent.key === 'direction' || intent.key === 'statuses')) {
    next[intent.key] = intent.value;
  } else if (intent.type === 'toggle' && intent.key === 'statuses') {
    const current = next.statuses || [];
    next.statuses = current.includes(intent.value)
      ? current.filter(value => value !== intent.value)
      : [...current, intent.value];
  } else {
    return query;
  }
  return next;
}

// The query as URL parameters; empty values are left out.
export function animeSeasonsParams(query = {}) {
  const params = {};
  for (const key of ['season', 'year', 'format', 'sort', 'direction']) {
    if (query[key] !== undefined && query[key] !== null && query[key] !== '') params[key] = String(query[key]);
  }
  if ((query.statuses || []).length) params.statuses = query.statuses.join(',');
  return params;
}

// Native loads the page model from the API; `request(path, { query })` resolves
// the parsed JSON of an authenticated /api/v1 call.
export function useAnimeSeasonsPage({ request }) {
  const [query, setQuery] = useState({});
  const [page, setPage] = useState(null);
  const [status, setStatus] = useState('loading');
  const [reload, setReload] = useState(0);
  const token = useRef(0);

  useEffect(() => {
    const mine = ++token.current;
    setStatus('loading');
    request('/api/v1/discover/anime-seasons/', { query: animeSeasonsParams(query) })
      .then(data => {
        if (mine !== token.current) return;
        setPage(data);
        setStatus(data?.state || 'ready');
      })
      .catch(() => { if (mine === token.current) setStatus('error'); });
  }, [request, query, reload]);

  // Intents build on the server's normalized query, so a sort or season the
  // server chose is kept when only another filter changes.
  const change = useCallback(intent => {
    setQuery(current => applyAnimeSeasonsIntent({ ...(page?.query || {}), ...current }, intent));
  }, [page]);

  return {
    page,
    status,
    change,
    step: target => change({ type: 'step', year: target.year, season: target.season }),
    retry: () => setReload(value => value + 1),
  };
}
