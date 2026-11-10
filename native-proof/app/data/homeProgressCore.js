// Request and state rules for the Home quick progress changer.

// The progress route takes the library row's identity; a season addresses the
// show plus its season number, every other type its own provider id.
export function adjustProgressRequest(identity, operation) {
  const type = identity.mediaType === 'season' || identity.mediaType === 'episode'
    ? 'tv'
    : identity.mediaType;
  const season = identity.mediaType === 'season' && identity.seasonNumber != null
    ? `/${encodeURIComponent(identity.seasonNumber)}`
    : '';
  const path = `/api/v1/media/${encodeURIComponent(type)}/${encodeURIComponent(identity.source)}`
    + `/${encodeURIComponent(identity.mediaId)}${season}/progress/`;
  return [path, { method: 'POST', body: { operation } }];
}

// Fold the server's updated row back into the control's props.
export function progressFromResponse(current, row) {
  if (!row || row.progress == null) return current;
  const progress = Number(row.progress);
  const max = row.max_progress == null ? null : Number(row.max_progress);
  return {
    ...current,
    value: String(row.formatted_progress ?? row.progress),
    canDecrease: progress > 0,
    canIncrease: max == null || progress < max,
  };
}
