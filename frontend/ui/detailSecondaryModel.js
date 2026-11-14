const DEFAULT_ZONES = {
  sidebar: ['history', 'details', 'genres', 'studios', 'collection'],
  content: ['notes', 'related', 'seasons', 'episodes', 'cast', 'crew', 'recommendations', 'game_lengths'],
};

const DATE_KEYS = new Set(['start_date', 'end_date', 'publish_date', 'release_date', 'last_updated']);
const HIDDEN_DETAIL_KEYS = new Set(['themes', 'last_air_date', 'episodes', 'seasons']);

function display(value, unknown = 'Unknown') {
  if (value === null || value === undefined || value === '') return unknown;
  if (Array.isArray(value)) return value.map(item => display(item, unknown)).join(', ');
  if (typeof value === 'object') return display(value.name ?? value.title ?? value.label ?? value.value, unknown);
  return String(value);
}

function labelFor(key) {
  return key.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function dateValue(value, formatDate, unknown) {
  if (!value) return unknown;
  // The web preserves a publication's year/month precision instead of inventing a day.
  if (/^\d{4}(?:-\d{2})?$/.test(String(value))) return String(value);
  return formatDate(value) || unknown;
}

function factValues(value) {
  return (Array.isArray(value) ? value : [value]).map(text => ({ text }));
}

/** Shape the PWA's safe detail metadata into presentation-only rows. */
export function detailSecondaryModel(payload = {}, { formatDate = value => String(value || '') } = {}) {
  const secondary = payload.secondary || {};
  const details = secondary.details || payload.media_details || {};
  const labels = secondary.labels || {};
  const unknown = labels.unknown || 'Unknown';
  const authors = secondary.authors_linked || [];
  const studios = secondary.studios_linked || [];
  const formats = payload.book_formats || [];
  const suppressed = new Set(secondary.promotion?.suppressed_keys || []);
  const authorKeys = new Set(authors.length ? secondary.author_detail_keys || [] : []);
  const studioKeys = new Set(studios.length ? secondary.studio_detail_keys || [] : []);
  const facts = [];

  for (const [key, raw] of Object.entries(details)) {
    if (HIDDEN_DETAIL_KEYS.has(key) || authorKeys.has(key) || studioKeys.has(key)
      || (formats.length && key === secondary.book_formats_replaces)
      || (key === 'runtime' && details.total_runtime)) continue;
    let label = labelFor(key);
    let values;
    if (secondary.display_details?.[key] !== undefined) {
      values = factValues(secondary.display_details[key]);
      if (key === 'first_air_date') label = labels.airDates || 'Air Dates';
      if (key === 'runtime' || key === 'total_runtime') {
        label = labels.runtime || 'Runtime';
        if (key === 'total_runtime' && details.seasons) label += ` (${details.seasons} ${Number(details.seasons) === 1 ? 'season' : 'seasons'})`;
      }
    } else if (key === 'first_air_date') {
      label = labels.airDates || 'Air Dates';
      values = factValues([dateValue(raw, formatDate, unknown), details.last_air_date
        ? dateValue(details.last_air_date, formatDate, unknown) : ''].filter(Boolean).join(' – '));
    } else if (key === 'runtime' || key === 'total_runtime') {
      label = labels.runtime || 'Runtime';
      if (key === 'total_runtime' && details.seasons) {
        label += ` (${details.seasons} ${Number(details.seasons) === 1 ? 'season' : 'seasons'})`;
      }
      const episodes = details.episodes
        ? `${details.episodes} ${Number(details.episodes) === 1 ? 'episode' : 'episodes'}` : '';
      values = factValues([display(raw, unknown), episodes].filter(Boolean).join(' · '));
    } else if (DATE_KEYS.has(key)) {
      values = factValues(dateValue(raw, formatDate, unknown));
    } else if (key === 'format' && payload.identity?.media_type === 'anime') {
      values = factValues(labels.anime || 'Anime');
    } else {
      values = factValues(Array.isArray(raw) ? raw.map(value => display(value, unknown)) : display(raw, unknown));
    }
    facts.push({ key, label, values, promoted: suppressed.has(key) });
  }

  if (formats.length) facts.push({ key: 'book-formats', label: labels.format || 'Format', inline: true,
    values: formats.map(format => ({ text: format.label, href: format.href || '' })) });
  if (authors.length) facts.push({ key: 'authors', label: authors.length === 1 ? (labels.author || 'Author') : (labels.authors || 'Authors'),
    values: authors.map(author => ({ text: author.name, href: author.href || '', identity: author })) });

  const promoted = (secondary.promotion?.fields || []).map(fact => {
    if (fact.display_value !== undefined) return { key: fact.key, label: fact.label || labelFor(fact.key), value: display(fact.display_value, unknown) };
    let value = fact.value;
    if (fact.key === 'air_dates') value = (value || []).filter(Boolean).map(date => dateValue(date, formatDate, unknown)).join(' – ');
    else if (fact.key === 'release_date') value = dateValue(value, formatDate, unknown);
    else if (fact.key === 'episodes') value = `${value} ${Number(value) === 1 ? 'episode' : 'episodes'}`;
    else if (fact.key === 'locale' && value && typeof value === 'object') {
      const language = value.languages ? display(value.languages, unknown) : '';
      const country = value.country ? display(value.country, unknown) : '';
      value = language && country ? `${language} (${country})` : language || country;
    } else if (fact.key === 'total_runtime' && payload.identity?.media_type === 'tv' && details.episodes) {
      value = `${display(value, unknown)} · ${details.episodes} ${Number(details.episodes) === 1 ? 'episode' : 'episodes'}`;
    }
    return { key: fact.key, label: fact.label || labelFor(fact.key), value: display(value, unknown) };
  });

  const lengths = payload.game_lengths;
  const youtube = payload.youtube_watch;
  return {
    layout: payload.layout,
    publicView: Boolean(payload.public_view || payload.read_only),
    genres: (payload.tag_sections || []).find(group => group.title === 'Genres')?.entries?.map(entry => ({ label: entry.label, href: entry.url || '' }))
      || (payload.sections || []).find(section => section.id === 'genres')?.items?.map(label => ({ label: String(label), href: '' })) || [],
    facts,
    promoted,
    studios,
    watchProviders: secondary.watch_providers ?? null,
    watchProviderRegion: secondary.watch_provider_region ?? 'UNSET',
    labels,
    gameLengths: lengths || payload.identity?.media_type === 'game' ? {
      available: Boolean(lengths?.available), pending: Boolean(lengths?.pending || payload.game_lengths_pending),
      sourceLabel: lengths?.source_label || '', sourceUrl: lengths?.source_url || '',
      cards: (lengths?.cards || []).map(card => ({ label: card.label, value: card.value, count: card.count, glyph: card.glyph || '◷' })),
    } : null,
    youtubeWatch: youtube ? { seconds: youtube.seconds, hoursLabel: youtube.hours_label || '', videos: youtube.videos || 0 } : null,
  };
}

/** Missing layouts use the established default; explicit empty zones stay hidden. */
export function detailSecondaryOrder(layout, available, zone) {
  const zones = layout?.zones || layout;
  const order = zones?.[zone] ?? DEFAULT_ZONES[zone] ?? [];
  const seen = new Set();
  const rows = order.flatMap((key, index) => {
    if (!available.includes(key) || seen.has(key)) return [];
    seen.add(key);
    return [{ key, order: index }];
  });
  // The PWA's YouTube estimate is an unconfigured game summary with order zero.
  // It follows the first configured order-zero section and precedes later orders.
  if (zone === 'content' && available.includes('youtube_watch') && !seen.has('youtube_watch')) rows.push({ key: 'youtube_watch', order: 0 });
  return rows.sort((a, b) => a.order - b.order).map(row => row.key);
}
