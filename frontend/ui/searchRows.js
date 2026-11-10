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
