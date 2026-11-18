// Collapse older per-media status choices into a single permissive selection.
export function normalizeCalendarStatuses(available, saved) {
  const selected = new Set(Object.entries(available).flatMap(([type, statuses]) =>
    Array.isArray(saved?.[type]) ? saved[type] : statuses));
  return Object.fromEntries(Object.entries(available).map(([type, statuses]) =>
    [type, statuses.filter(status => selected.has(status))]));
}

export function toggleCalendarStatus(available, selectedByType, value) {
  const selected = Object.values(selectedByType).some(statuses => statuses.includes(value));
  return Object.fromEntries(Object.entries(available).map(([type, statuses]) => {
    const current = selectedByType[type] || [];
    return [type, selected ? current.filter(status => status !== value)
      : statuses.includes(value) ? [...current, value] : current];
  }));
}
