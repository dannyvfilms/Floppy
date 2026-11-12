// Turns the destination URL the server sends for a Home row title into the
// params the native Library screen takes. Web opens /medialist/<type>?...;
// native opens Library with the same filters. Rows with no medialist
// destination (Up Next, mixed media, custom lists) return null and stay plain.
const STATUS_VALUES = {
  planning: 'planning',
  'in progress': 'in_progress',
  paused: 'paused',
  completed: 'completed',
  dropped: 'dropped',
  'no status': 'no_status',
};

export function libraryParamsForRowUrl(href) {
  if (typeof href !== 'string') return null;
  const match = href.match(/^\/medialist\/([^/?#]+)\/?(?:\?([^#]*))?(?:#.*)?$/);
  if (!match) return null;
  const mediaType = decodeURIComponent(match[1]);
  const source = new URLSearchParams(match[2] || '');
  const query = new URLSearchParams();
  source.forEach((value, key) => {
    if (key !== 'status') { query.append(key, value); return; }
    const mapped = STATUS_VALUES[value.trim().toLowerCase()];
    // "All" means no status filter; unknown labels are dropped, not guessed.
    if (mapped) query.append('status', mapped);
  });
  return { mediaType, query: query.toString() };
}
