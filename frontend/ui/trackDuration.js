// Typed durations for the Tracking form: parse what a person types, format it as hrs and min.
export function parseTrackDurationMinutes(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return null;
  if (/^\d+(?:\.\d+)?$/.test(text)) {
    const amount = Number.parseFloat(text);
    return Number.isFinite(amount) && amount >= 0 ? Math.trunc(amount * 60) : null;
  }
  if (text.includes(':')) {
    const chunks = text.split(':');
    if (chunks.length !== 2 || !/^\d+$/.test(chunks[0]) || !/^\d+$/.test(chunks[1])) return null;
    const minutes = Number.parseInt(chunks[1], 10);
    if (minutes > 59) return null;
    return Number.parseInt(chunks[0], 10) * 60 + minutes;
  }
  const unitPattern = /(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min)/g;
  const matches = [];
  let match = unitPattern.exec(text);
  while (match) {
    matches.push(match);
    match = unitPattern.exec(text);
  }
  if (!matches.length || text.replace(unitPattern, '').trim()) return null;
  let total = 0;
  for (const entry of matches) {
    const amount = Number.parseFloat(entry[1]);
    if (!Number.isFinite(amount)) return null;
    total += entry[2].startsWith('h') ? amount * 60 : amount;
  }
  return Math.trunc(total);
}

// Same wording as the history feed: 135 -> "2h 15min", 120 -> "2h", 45 -> "45min".
export function formatTrackDuration(minutes) {
  const total = Math.trunc(minutes);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (!hours) return `${rest}min`;
  return rest ? `${hours}h ${rest}min` : `${hours}h`;
}
