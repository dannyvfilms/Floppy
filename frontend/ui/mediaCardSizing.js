// Width used by the Lists page's responsive media-card grid.
export function mediaCardGridWidth(viewportWidth) {
  const columns = viewportWidth >= 760 ? 4 : viewportWidth >= 560 ? 3 : 2;
  return Math.min(184, Math.max(128, (viewportWidth - 32 - (columns - 1) * 12) / columns));
}

// Home playback spans the same number of regular cards as the user's mobile
// grid preference, or two cards on desktop. Compact phone cards use the Home
// shelf's shared 110 pt width.
export function playbackCardWidth(viewportWidth, mobileGridLayout = 'compact') {
  if (viewportWidth >= 769) return mediaCardGridWidth(viewportWidth) * 2 + 12;

  const compact = mobileGridLayout !== 'comfortable';
  const columns = compact ? 3 : 2;
  const gap = compact ? 16 : 12;
  const cardCap = compact ? 110 : 168;
  const width = Math.min(cardCap, (viewportWidth - 32 - (columns - 1) * gap) / columns);
  return width * columns + (columns - 1) * gap;
}
