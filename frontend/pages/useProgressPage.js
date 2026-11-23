import { useCallback, useEffect, useRef, useState } from 'react';

// Loading and view state for the Progress page, shared by web and Expo. The
// caller supplies `request(path, { query })`, which resolves the parsed JSON of
// a same-origin (web) or authenticated (native) /api/v1 call.

// The filter toolbar's options, in the shape the media list uses. A sort plus its
// direction maps to the server's least/most orders ("asc" is least first).
export const progressSorts = [
  { value: 'time_left', label: 'Time left' },
  { value: 'episodes_left', label: 'Episodes left' },
];
export const progressStatuses = [
  { value: 'in_progress', label: 'In progress' },
  { value: 'finished', label: 'Finished' },
];

function serverQuery({ sort, direction, statuses }) {
  const order = sort === 'episodes_left' ? 'episodes' : 'time';
  return { sort: `${direction === 'desc' ? 'most' : 'least'}_${order}`, statuses: statuses.join(',') || 'in_progress' };
}

function breakdownPath(row) {
  return `/api/v1/media/tv/${encodeURIComponent(row.source)}/${encodeURIComponent(row.media_id)}/progress-card/`;
}

export function useProgressPage({ request }) {
  const [filters, setFilters] = useState({ sort: 'time_left', direction: 'asc', statuses: ['in_progress'] });
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [seasons, setSeasons] = useState({});
  const [dialog, setDialog] = useState(null);
  const [reload, setReload] = useState(0);
  const token = useRef(0);

  useEffect(() => {
    const mine = ++token.current;
    setStatus('loading');
    request('/api/v1/progress/', { query: serverQuery(filters) })
      .then(data => {
        if (mine !== token.current) return;
        setRows(data.results || []);
        setSummary(data.summary || null);
        setHasMore(Boolean(data.pagination?.has_more));
        setStatus((data.results || []).length ? 'ready' : 'empty');
      })
      .catch(() => { if (mine === token.current) setStatus('error'); });
  }, [request, filters, reload]);

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore) return;
    const mine = token.current;
    setLoadingMore(true);
    request('/api/v1/progress/', { query: { ...serverQuery(filters), offset: rows.length } })
      .then(data => {
        if (mine !== token.current) return;
        setRows(current => [...current, ...(data.results || [])]);
        setHasMore(Boolean(data.pagination?.has_more));
      })
      .catch(() => { if (mine === token.current) setHasMore(false); })
      .finally(() => setLoadingMore(false));
  }, [request, filters, rows.length, hasMore, loadingMore]);

  const toggleSeasons = useCallback(row => {
    const open = !expanded[row.id];
    setExpanded(current => ({ ...current, [row.id]: open }));
    if (!open || seasons[row.id]?.status === 'ready') return;
    setSeasons(current => ({ ...current, [row.id]: { status: 'loading', rows: [] } }));
    request(breakdownPath(row))
      .then(payload => setSeasons(current => ({
        ...current,
        [row.id]: { status: 'ready', rows: (payload.model?.seasons || []).filter(season => !season.dropped && season.number > 0) },
      })))
      .catch(() => setSeasons(current => ({ ...current, [row.id]: { status: 'error', rows: [] } })));
  }, [request, expanded, seasons]);

  const openDialog = useCallback(row => {
    setDialog({ row, status: 'loading', model: null });
    request(breakdownPath(row))
      .then(payload => setDialog(current => (current?.row.id === row.id ? { row, status: 'ready', model: payload.model } : current)))
      .catch(() => setDialog(current => (current?.row.id === row.id ? { row, status: 'error', model: null } : current)));
  }, [request]);

  // Applies a FilterBar intent: set a key, toggle a status, or clear back to the defaults.
  const changeFilter = useCallback(intent => {
    setFilters(current => {
      if (intent.type === 'clear') return { sort: 'time_left', direction: 'asc', statuses: ['in_progress'] };
      if (intent.type === 'set') return { ...current, [intent.key]: intent.value };
      if (intent.type === 'toggle') {
        const has = current[intent.key].includes(intent.value);
        const next = has ? current[intent.key].filter(value => value !== intent.value) : [...current[intent.key], intent.value];
        return { ...current, [intent.key]: next };
      }
      return current;
    });
  }, []);

  return {
    filters, changeFilter, rows, summary, hasMore, status,
    loadingMore, loadMore, expanded, seasons, toggleSeasons,
    dialog, openDialog, closeDialog: () => setDialog(null),
    retry: () => setReload(value => value + 1),
  };
}
