// The division frame is measured in the containing view, not screen coordinates.
export function menuGeometry(width, hingeStatus, division) {
  const partial = hingeStatus === 'partiallyOpen' && division
    && division.x > 0 && division.x < width;
  const full = hingeStatus === 'closed' || (!partial && width < 600);
  if (full) return { full: true, menuWidth: width, gap: 0 };
  if (partial) return {
    full: false,
    menuWidth: division.x,
    gap: Math.min(division.width, width - division.x),
  };
  return { full: false, menuWidth: Math.min(288, width), gap: 0 };
}
