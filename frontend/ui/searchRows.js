import { useEffect, useState } from 'react';

// Search rows load more the way Home rows do: ask the server for the row's next page and
// append it. Web and native share this, so a row pages the same way on both.

// The next page's request for one row. Your library pages by offset, a provider by page number.
export function searchRowParams(row, { query = '', mediaType = '' } = {}) {
  const params = { q: query, media_type: mediaType, row: String(row.rowId) };
  if (String(row.rowId).startsWith('online:')) {
    params.page = String((row.page || 1) + 1);
  } else {
    params.offset = String(row.loadedCount ?? (row.items || []).length);
  }
  return params;
}

export function searchRowUrl(row, context, base = '') {
  return `${base}/search/results?${new URLSearchParams(searchRowParams(row, context))}`;
}

export function mergeSearchRowPage(row, page) {
  if (!page) return row;
  const known = new Set((row.items || []).map(item => item.id));
  const fresh = (page.items || []).filter(item => !known.has(item.id));
  return {
    ...row,
    items: [...(row.items || []), ...fresh],
    loadedCount: (row.items || []).length + fresh.length,
    total: page.total ?? row.total,
    page: page.page ?? row.page,
  };
}

// The first page of one provider's row. The page asks for each provider on its own, so a
// fast one shows its row without waiting for a slow one.
export function onlineRowParams(source, { query = '', mediaType = '' } = {}) {
  return { q: query, media_type: mediaType, row: source.rowId, page: '1' };
}

/**
 * Library rows come with the page; provider rows stream in as each provider answers.
 * Returns the rows to draw (library first, providers in their listed order), the notes
 * for providers that failed, and whether any provider is still being asked.
 * `loadOnlineRow(source)` resolves to `{ row, unavailable }`.
 */
export function useStreamedRows({ rows = [], onlineSources = [], loadOnlineRow, resetKey = '' }) {
  const [arrived, setArrived] = useState({});
  const [failed, setFailed] = useState([]);
  const [done, setDone] = useState(0);
  const sourcesKey = onlineSources.map(item => item.rowId).join(',');
  useEffect(() => {
    setArrived({});
    setFailed([]);
    setDone(0);
    if (!loadOnlineRow || !onlineSources.length) return undefined;
    let cancelled = false;
    onlineSources.forEach(source => {
      Promise.resolve()
        .then(() => loadOnlineRow(source))
        .then(result => {
          if (cancelled) return;
          if (result?.row) setArrived(current => ({ ...current, [source.rowId]: result.row }));
          if (result?.unavailable) setFailed(current => [...current, result.unavailable]);
        })
        .catch(() => { if (!cancelled) setFailed(current => [...current, source.label]); })
        .finally(() => { if (!cancelled) setDone(current => current + 1); });
    });
    return () => { cancelled = true; };
  }, [sourcesKey, resetKey, loadOnlineRow]);
  const online = onlineSources.map(item => arrived[item.rowId]).filter(Boolean);
  return {
    rows: [...rows, ...online],
    failed,
    pending: Boolean(loadOnlineRow) && done < onlineSources.length,
  };
}
