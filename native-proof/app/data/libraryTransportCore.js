import { formatUserDate } from './userDate.js';

const STATUS_LABELS = {
  0: 'Planning',
  1: 'In progress',
  2: 'Paused',
  3: 'Completed',
  4: 'Dropped',
};

const STATUS_RANK = {
  Planning: 0,
  'In progress': 1,
  Completed: 2,
  Paused: 3,
  Dropped: 4,
};

const MEDIA_LABELS = {
  movie: 'Movie',
  tv: 'Show',
  season: 'Season',
  episode: 'Episode',
  anime: 'Anime',
  book: 'Book',
  comic: 'Comic',
  comicissue: 'Comic Issue',
  manga: 'Manga',
  game: 'Game',
  boardgame: 'Board Game',
  music: 'Music',
  podcast: 'Podcast',
  video: 'Video',
};

// Library vocabularies the API accepts but does not publish as option
// metadata. These mirror the server sources exactly: MediaTypes, MediaStatusChoices and
// MediaSortChoices with the per-type guards from media_list_views.py.
const MEDIA_TYPE_PLURALS = {
  movie: 'Movies',
  tv: 'TV Shows',
  season: 'TV Seasons',
  episode: 'Episodes',
  anime: 'Anime',
  book: 'Books',
  comic: 'Comics',
  comicissue: 'Comic Issues',
  manga: 'Manga',
  game: 'Games',
  boardgame: 'Board Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

// Status query values follow Status.value.lower() plus the shared
// MEDIA_LIST_NO_STATUS marker (src/app/media_list_filters.py).
const STATUS_QUERY_OPTIONS = [
  { value: 'no_status', label: 'No Status' },
  { value: 'completed', label: 'Completed' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'planning', label: 'Planning' },
  { value: 'paused', label: 'Paused' },
  { value: 'dropped', label: 'Dropped' },
];

// Tracker status labels accepted by the per-item PATCH body.
export const STATUS_TRACK_OPTIONS = [
  { value: 'Planning', label: 'Planning' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Dropped', label: 'Dropped' },
  { value: 'no_status', label: 'No Status' },
];

// MediaSortChoices labels (src/users/models.py) with the web END_DATE
// relabels (Last Played/Read/Listened) applied per media type.
const SORT_CHOICES = [
  { value: 'score', label: 'Rating' },
  { value: 'critic_rating', label: 'Critic Rating' },
  { value: 'title', label: 'Title' },
  { value: 'author', label: 'Author' },
  { value: 'popularity', label: 'Popularity' },
  { value: 'progress', label: 'Progress' },
  { value: 'runtime', label: 'Runtime' },
  { value: 'time_to_beat', label: 'Time to Beat' },
  { value: 'platform', label: 'Platform' },
  { value: 'plays', label: 'Plays' },
  { value: 'time_watched', label: 'Time Watched' },
  { value: 'release_date', label: 'Release Date' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'start_date', label: 'Start Date' },
  { value: 'end_date', label: 'Last Watched' },
  { value: 'next_episode_air_date', label: 'Episode Air Date' },
  { value: 'time_left', label: 'Time Left' },
];

// _sort_type_guards from src/app/media_list_views.py.
const SORT_TYPE_GUARDS = {
  progress: types => !types.has('movie'),
  time_left: types => types.has('tv'),
  runtime: types => types.has('movie') || types.has('tv') || types.has('anime'),
  popularity: types => types.has('movie') || types.has('tv') || types.has('anime'),
  time_to_beat: types => types.has('game'),
  platform: types => types.has('game'),
  plays: types => types.has('movie') || types.has('tv') || types.has('anime'),
  time_watched: types => types.has('movie') || types.has('tv') || types.has('anime'),
  next_episode_air_date: types => types.has('tv') || types.has('season') || types.has('anime'),
  critic_rating: types => CRITIC_RATING_TYPES.has(...types),
  author: types => AUTHOR_TYPES.has(...types),
};

// CRITIC_RATING_MEDIA_TYPES / AUTHOR_FILTER_MEDIA_TYPES.
const CRITIC_RATING_TYPES = new Set([
  'tv', 'season', 'movie', 'anime', 'manga', 'game', 'boardgame', 'book', 'comic',
]);
const AUTHOR_TYPES = new Set(['book', 'manga', 'comic', 'comicissue', 'video']);

const END_DATE_LABELS = {
  game: 'Last Played',
  boardgame: 'Last Played',
  book: 'Last Read',
  comic: 'Last Read',
  comicissue: 'Last Read',
  manga: 'Last Read',
  music: 'Last Listened',
  podcast: 'Last Listened',
};

// MEDIA_LIST_SORT_DEFAULTS_ASC: sorts that read ascending by default.
const ASCENDING_DEFAULT_SORTS = new Set([
  'author', 'popularity', 'runtime', 'start_date', 'title',
  'next_episode_air_date', 'time_left', 'time_to_beat', 'platform',
]);

function resultList(payload) {
  if (Array.isArray(payload)) return payload;
  return payload && Array.isArray(payload.results) ? payload.results : [];
}

function numericDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.getUTCFullYear() * 10000 + (date.getUTCMonth() + 1) * 100 + date.getUTCDate();
}

function dateLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function yearLabel(value) {
  if (!value) return '';
  const year = new Date(value).getUTCFullYear();
  return Number.isNaN(year) ? '' : String(year);
}

function runtimeLabel(item) {
  if (item.runtime) return String(item.runtime);
  const minutes = Number(item.runtime_minutes);
  if (!Number.isFinite(minutes) || minutes <= 0) return '';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}m`;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function progressText(row, unit) {
  const progress = row.progress;
  if (progress == null) return { text: '', maxText: '' };
  if (unit === 'plays') {
    return { text: String(progress), maxText: progress === 1 ? ' play' : ' plays' };
  }
  if (unit === 'minutes') {
    const minutes = Number(progress);
    if (!Number.isFinite(minutes)) return { text: String(progress), maxText: '' };
    const hours = Math.floor(minutes / 60);
    const rest = Math.round(minutes % 60);
    const label = hours ? `${hours}h${rest ? ` ${rest}m` : ''}` : `${rest}m`;
    return { text: label, maxText: ' played' };
  }
  if (unit === 'pages' || unit === 'chapters' || unit === 'issues') {
    return { text: String(progress), maxText: ` ${unit}` };
  }
  if (unit === 'percent') {
    return { text: `${progress}%`, maxText: '' };
  }
  const left = row.episodes_left;
  if (left != null) {
    return { text: String(progress), maxText: ` / ${Number(progress) + Number(left)} episodes` };
  }
  return { text: String(progress), maxText: ' episodes' };
}

// A text cell: the value, or the web's placeholder in the muted tone.
function plainCell(value, placeholder, format = String) {
  const has = value !== undefined && value !== null && value !== '';
  return { kind: 'text', text: has ? format(value) : placeholder, muted: !has };
}

// The web's labels for the sources whose capitals a plain capitalize gets wrong
// (app_tags.entry_source_label); text a person typed is shown as typed.
const ENTRY_SOURCE_LABELS = {
  anilist: 'AniList',
  audiobookshelf: 'Audiobookshelf',
  gpodder: 'gPodder',
  imdb: 'IMDb',
  koreader: 'KOReader',
  lastfm: 'Last.fm',
  listenbrainz: 'ListenBrainz',
  myanimelist: 'MyAnimeList',
  simkl: 'SIMKL',
  youtube: 'YouTube',
};

export function entrySourceLabel(value) {
  const text = String(value || '').trim();
  if (!text || text !== text.toLowerCase()) return text;
  if (ENTRY_SOURCE_LABELS[text]) return ENTRY_SOURCE_LABELS[text];
  const spaced = text.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function mediaRowFromPayload(row) {
  if (row.group) {
    const group = row.group;
    return {
      id: `group:${group.group_key}`, groupKey: group.group_key,
      title: group.name || group.group_key,
      identity: { mediaType: 'game' },
      cells: {
        image: { src: group.image || null },
        score: { rated: group.score != null, text: group.score == null ? '' : Number(group.score).toFixed(1) },
      },
      group,
    };
  }
  const item = row.item || {};
  const mediaType = item.library_media_type || item.media_type || '';
  const status = STATUS_LABELS[row.status] || '';
  const progress = progressText(row, row.progress_unit);
  const release = item.release_datetime;
  const genres = Array.isArray(item.genres) ? item.genres : [];
  const tagNames = Array.isArray(row.tags) ? row.tags : [];
  // The numeric item id: bulk actions and "select all matching" speak in it.
  const id = row.id != null ? String(row.id) : String(row.item_id || '');
  const title = item.title || '';
  return {
    id,
    entryId: row.entry_id == null ? null : String(row.entry_id),
    title,
    identity: {
      mediaType,
      source: item.source,
      mediaId: item.media_id,
      libraryMediaType: item.library_media_type,
      itemId: row.id,
      title,
      image: item.image || null,
    },
    sort: {
      score: row.score == null ? null : Number(row.score),
      progress: typeof row.progress === 'number' ? row.progress : null,
      status: STATUS_RANK[status] ?? null,
      runtime: item.runtime_minutes ?? null,
      time_watched: null,
      release_date: numericDate(release),
      date_added: numericDate(row.created_at),
      genres: genres.join(', '),
    },
    track: {
      mediaType,
      progressLabel: row.progress_unit === 'minutes' ? 'Minutes played'
        : row.progress_unit === 'pages' ? 'Pages read'
          : row.progress_unit === 'plays' ? 'Times watched'
            : 'Progress',
      progressValue: row.progress == null ? '' : String(row.progress),
      progressMax: row.episodes_left != null && row.progress != null
        ? Number(row.progress) + Number(row.episodes_left)
        : null,
      startDate: row.start_date || '',
      endDate: row.end_date || '',
    },
    cells: {
      image: { kind: 'image', src: item.image || null, alt: title },
      title: { kind: 'title', text: title, href: `#open:${id}` },
      media_type: { kind: 'text', text: MEDIA_LABELS[mediaType] || mediaType, muted: true },
      score: {
        kind: 'score',
        rated: row.score != null,
        text: row.score == null ? '' : String(row.score),
      },
      progress: { kind: 'progress', text: progress.text, maxText: progress.maxText, note: 'Total' },
      status: { kind: 'status', text: status || '-', muted: !status },
      runtime: { kind: 'text', text: runtimeLabel(item) || '--', muted: !runtimeLabel(item) },
      critic_rating: plainCell(item.imdb_rating ?? item.provider_rating, '--', value => Number(value).toFixed(1)),
      time_watched: plainCell(
        mediaType === 'movie' && status === 'Completed' ? runtimeLabel(item) : '',
        '--',
      ),
      popularity: plainCell(item.provider_popularity, '--', value => String(Math.round(Number(value)))),
      tags: plainCell(tagNames.join(', '), '-'),
      release_date: plainCell(formatUserDate(release), '-'),
      date_added: plainCell(formatUserDate(row.created_at), '-'),
      start_date: plainCell(formatUserDate(row.start_date), '-'),
      end_date: plainCell(formatUserDate(row.end_date), '-'),
      source: plainCell(entrySourceLabel(row.source), '--'),
      notes: plainCell(row.notes, '-'),
      description: plainCell(item.synopsis, '-'),
      genres: { kind: 'genres', items: genres.map(label => ({ label })) },
    },
    media: row,
  };
}

export function mediaRowsFromPayload(payload) {
  const results = Array.isArray(payload) ? payload : payload?.results || [];
  return results.map(mediaRowFromPayload);
}

export function tagOptionsFromPayload(payload) {
  return resultList(payload)
    .map(tag => ({
      id: String(tag.id ?? ''),
      name: String(tag.name ?? '').trim(),
      count: Number(tag.item_count ?? 0),
    }))
    .filter(tag => tag.id && tag.name);
}

export function listOptionsFromPayload(payload) {
  return resultList(payload)
    .map(list => ({
      id: String(list.id ?? ''),
      name: String(list.name ?? '').trim(),
    }))
    .filter(list => list.id && list.name);
}

// Card actions the native action host understands: the track and lists
// modals resolve through the row identity, the history link follows the
// same web href the drawer uses.
export function cardActionsFor(title, identity) {
  return {
    href: '',
    items: [
      { kind: 'modal', modal: 'track', title: 'Edit tracking', glyph: '✎', media: identity },
      { kind: 'modal', modal: 'lists', title: 'Add to custom lists', glyph: '☰', media: identity },
      { kind: 'link', title: 'View your activity history', glyph: '◷', href: '/history', media: identity },
    ],
    ordering: null,
    modals: { track: 'track', lists: 'lists' },
    csrfToken: '',
    clickable: true,
    title,
    media: identity,
  };
}

// The web library card shows the title and rating; below it the page prints
// the value of the active sort (date added, release date, progress, ...).
function sortValueText(row, sort) {
  const cells = row.cells || {};
  const media = row.media || {};
  const dated = value => (value && value !== '-' && value !== '—' ? value : '');
  if (sort === 'date_added') return dated(cells.date_added?.text);
  if (sort === 'release_date') return dateLabel(media.item?.release_datetime);
  if (sort === 'start_date') return dateLabel(media.start_date);
  if (sort === 'end_date') return dateLabel(media.end_date);
  if (sort === 'progress') {
    return [cells.progress?.text, cells.progress?.maxText].filter(Boolean).join('').trim();
  }
  return '';
}

// Build the shared MediaCard model from one real library row so the grid
// layout renders the same rows the table does.
export function cardModelFromRow(row, { sort } = {}) {
  const identity = row?.identity || {};
  const cells = row.cells || {};
  const sortText = sortValueText(row, sort);
  const score = cells.score?.rated ? Number(cells.score.text) : null;
  return {
    mediaType: identity.mediaType || '',
    identity,
    shape: 'poster',
    video: identity.mediaType === 'video',
    image: { src: cells.image?.src || null, fallback: '', source: 'primary' },
    title: row.title || '',
    altTitle: null,
    // The web library grid shows no status badge on its cards.
    statusChip: null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: sortText ? [{ join: 'dot', parts: [{ text: sortText }] }] : [],
    rating: score != null && Number.isFinite(score)
      ? { label: String(cells.score.text), value: score, scaleMax: 10, rateLabel: 'Rate' }
      : null,
    ratingEditable: true,
    actions: cardActionsFor(row.title || '', identity),
  };
}

export function cardModelsFromRows(rows = [], options = {}) {
  return (Array.isArray(rows) ? rows : []).map(row => ({
    key: row.entryId ? `${row.id}:${row.entryId}` : String(row.id ?? ''),
    model: row.group ? {
      ...(row.group.card || cardModelFromRow(row, options)), actions: null, ratingEditable: false, hoverMetadata: true,
    } : cardModelFromRow(row, options),
    row,
  }));
}

// Turn per-item bulk outcomes into one honest summary line. Every count
// comes from the actual request results; failures carry the first message.
export function summarizeBulkOutcome(outcome) {
  if (outcome?.message) return String(outcome.message);
  const done = Number(outcome?.done ?? 0);
  const failed = Number(outcome?.failed ?? 0);
  const skipped = Number(outcome?.skipped ?? 0);
  const parts = [];
  if (done) parts.push(`${done} updated`);
  if (skipped) parts.push(`${skipped} skipped`);
  if (failed) parts.push(`${failed} failed`);
  if (!parts.length) return 'Nothing changed.';
  const text = parts.join(', ');
  const message = outcome?.firstError ? ` ${outcome.firstError}` : '';
  return `${text}.${message}`.trim();
}

export function libraryMediaTypeOptions() {
  return Object.keys(MEDIA_TYPE_PLURALS).map(value => ({ value, label: MEDIA_TYPE_PLURALS[value] }));
}

// config.py verbs behind "what you've {verb}" in the web empty state.
const PAST_VERBS = {
  book: 'read', comic: 'read', comicissue: 'read', manga: 'read',
  game: 'played', boardgame: 'played', music: 'listened', podcast: 'listened',
};

export function libraryPastVerb(mediaType) {
  return PAST_VERBS[mediaType] || 'watched';
}

export function libraryMediaTypeTitle(mediaType) {
  return MEDIA_TYPE_PLURALS[mediaType] || 'Library';
}

export function libraryStatusOptions() {
  return STATUS_QUERY_OPTIONS.map(option => ({ ...option }));
}

export function defaultSortDirection(sort) {
  return ASCENDING_DEFAULT_SORTS.has(sort) ? 'asc' : 'desc';
}

export function librarySortOptions(mediaType) {
  const types = new Set(String(mediaType || '').split(',').filter(Boolean));
  return SORT_CHOICES
    .filter(choice => !SORT_TYPE_GUARDS[choice.value] || SORT_TYPE_GUARDS[choice.value](types))
    .map(choice => ({
      value: choice.value,
      label: choice.value === 'end_date' ? (END_DATE_LABELS[mediaType] || choice.label) : choice.label,
    }));
}

// Filter bar options for one library page. The media-type picker exists only
// on the all-types page, like the web passes filter_show_media_types only for
// the mixed view. Sections come from libraryFilterSections.
export function libraryFilterOptions({ mediaType, includeMediaTypes = false } = {}) {
  const options = {
    statuses: libraryStatusOptions(),
    sorts: librarySortOptions(mediaType),
    views: [
      { value: 'table', label: 'Table' },
      { value: 'grid', label: 'Grid' },
    ],
    ranges: [
      { key: 'rating', label: 'Rating', type: 'number', placeholder: '0-10' },
      {
        key: 'dateAdded',
        label: 'Date added',
        type: 'date',
        placeholder: 'YYYY-MM-DD',
        relative: true,
        units: [
          { value: 'days', label: 'Days' },
          { value: 'weeks', label: 'Weeks' },
          { value: 'months', label: 'Months' },
          { value: 'years', label: 'Years' },
        ],
      },
      {
        key: 'release',
        label: 'Release date',
        type: 'date',
        placeholder: 'YYYY-MM-DD',
        relative: true,
        units: [
          { value: 'days', label: 'Days' },
          { value: 'weeks', label: 'Weeks' },
          { value: 'months', label: 'Months' },
          { value: 'years', label: 'Years' },
        ],
      },
      {
        key: 'completed',
        label: 'Completed date',
        type: 'date',
        placeholder: 'YYYY-MM-DD',
        relative: true,
        units: [
          { value: 'days', label: 'Days' },
          { value: 'weeks', label: 'Weeks' },
          { value: 'months', label: 'Months' },
          { value: 'years', label: 'Years' },
        ],
      },
    ],
    sections: [],
  };
  if (includeMediaTypes) {
    options.mediaTypes = libraryMediaTypeOptions();
  }
  return options;
}

const STATIC_SECTIONS = {
  rating: ['Rating', 'Any Rating', [['rated', 'Rated'], ['not_rated', 'Not Rated']]],
  collection: ['Collection', 'Any Collection', [['collected', 'Collected'], ['not_collected', 'Not Collected']]],
  progress: ['Progress', 'Any Progress', [['not_caught_up', 'Not Caught Up'], ['caught_up', 'Caught Up']]],
  release: ['Released', 'All', [['released', 'Released'], ['not_released', 'Not Released']]],
};

function staticSection(key) {
  const [label, any, entries] = STATIC_SECTIONS[key];
  return {
    key,
    label,
    state: key,
    type: 'single',
    clearValue: 'all',
    options: [{ value: 'all', label: any }, ...entries.map(([value, text]) => ({ value, label: text }))],
  };
}

function optionSection(key, label, entries, extra = {}) {
  const options = (Array.isArray(entries) ? entries : [])
    .map(entry => (typeof entry === 'string'
      ? { value: entry, label: entry }
      : { value: String(entry.value), label: String(entry.label ?? entry.value) }))
    .filter(option => option.value);
  if (!options.length) return null;
  return { key, label, state: key, type: 'single', clearValue: '', searchable: true, options, ...extra };
}

const MODES = [
  { value: 'or', label: 'Any' },
  { value: 'and', label: 'All' },
  { value: 'not', label: 'Not' },
];

// Filter sections in the order of the web filter menu (filter_menu.html). The
// option lists come from GET /api/v1/media/<type>/filter-options/, which uses
// the same builder as the web menu; a section with nothing to choose is left
// out, like the web does.
export function libraryFilterSections(mediaType, data) {
  const info = data || {};
  const sections = [staticSection('rating'), staticSection('collection')];
  if (info.show_progress) sections.push(staticSection('progress'));
  sections.push(
    optionSection('genre', 'Genre', info.genres),
    optionSection('implied_genre', 'Implied Genre', info.implied_genres),
    optionSection('year', 'Date', info.years),
    staticSection('release'),
    optionSection('source', 'Source', info.sources),
    optionSection('media_status', 'Availability', info.media_statuses),
  );
  if (info.show_languages) sections.push(optionSection('language', 'Language', info.languages));
  if (info.show_countries) sections.push(optionSection('country', 'Country', info.countries));
  if (info.show_platforms) {
    sections.push(optionSection('platform', 'Platform', info.platforms, {
      type: 'multi',
      modes: MODES,
      modeState: 'platformMode',
      modeValue: 'or',
    }));
  }
  if (info.show_formats) sections.push(optionSection('format', 'Format', info.formats));
  if (info.show_authors) {
    sections.push(optionSection('author', info.author_is_channel ? 'Channel' : 'Author', info.authors));
  }
  if (info.show_providers) sections.push(optionSection('provider', 'Streaming Service', info.providers));
  const tags = (Array.isArray(info.tags) ? info.tags : [])
    .map(tag => ({ value: String(tag.name), label: tag.count ? `${tag.name} (${tag.count})` : String(tag.name) }));
  if (tags.length) {
    sections.push({
      key: 'tags',
      label: 'Tag',
      state: 'selectedTags',
      type: 'multi',
      clearValue: '',
      searchable: true,
      modes: MODES,
      modeState: 'tagMode',
      modeValue: 'or',
      options: tags,
    });
  }
  return sections.filter(Boolean);
}

export function defaultLibraryFilters() {
  return {
    mediaTypes: [],
    statuses: [],
    sort: 'score',
    direction: 'desc',
    view: 'grid',
    ranges: {
      rating: { from: '', to: '', within: '', unit: 'days' },
      dateAdded: { from: '', to: '', within: '', unit: 'days' },
      release: { from: '', to: '', within: '', unit: 'days' },
      completed: { from: '', to: '', within: '', unit: 'days' },
    },
    fields: { tags: [], platform: [], rating: 'all', collection: 'all', progress: 'all', release: 'all' },
    modes: { tags: 'or', platform: 'or' },
  };
}

function cleanRatingBound(value) {
  const text = String(value ?? '').trim();
  return /^\d+(\.\d+)?$/.test(text) ? text : '';
}

function cleanDate(value) {
  const text = String(value ?? '').trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : '';
}

function cleanWithin(value) {
  const text = String(value ?? '').trim();
  return /^\d{1,3}$/.test(text) && Number(text) > 0 ? text : '';
}

function rangeQuery(query, prefix, range) {
  const value = range || {};
  const within = cleanWithin(value.within);
  if (within) {
    query[`${prefix}_within`] = within;
    query[`${prefix}_within_unit`] = ['days', 'weeks', 'months', 'years'].includes(value.unit)
      ? value.unit
      : 'days';
    return;
  }
  const from = cleanDate(value.from);
  const to = cleanDate(value.to);
  if (from) query[`${prefix}_from`] = from;
  if (to) query[`${prefix}_to`] = to;
}

// Single-value filters share their field key with the API parameter.
const SINGLE_FIELD_PARAMS = [
  'rating', 'collection', 'progress', 'release', 'genre', 'implied_genre', 'year',
  'source', 'media_status', 'language', 'country', 'origin', 'format', 'author', 'provider',
];
// [field key, API parameter, API mode parameter]; tags filter by name.
const MULTI_FIELD_PARAMS = [
  ['tags', 'tag', 'tag_mode'],
  ['platform', 'platform', 'platform_mode'],
];

// Map the filter bar state onto the shared media-list query contract
// (parse_media_list_filters, strict API mode: comma-separated values).
export function libraryQuery({
  mediaType,
  limit = 30,
  offset = 0,
  search,
  status,
  sort,
  direction,
  filters,
} = {}) {
  const query = { limit, offset };
  if (search) query.search = search;
  if (status) query.status = status;
  if (sort) query.sort = sort;
  if (direction) query.direction = direction;
  if (!filters) return query;

  const state = filters;
  const selectedTypes = Array.isArray(state.mediaTypes) ? state.mediaTypes.filter(Boolean) : [];
  if (!mediaType && selectedTypes.length === 1) {
    query.media_type = selectedTypes[0];
  }
  const statuses = Array.isArray(state.statuses) ? state.statuses.filter(Boolean) : [];
  if (statuses.length) query.status = statuses.join(',');
  if (state.sort) query.sort = state.sort;
  if (state.direction) query.direction = state.direction;
  if (state.initial) query.initial = state.initial;
  if (state.separateEntries) query.separate_entries = '1';
  if (mediaType === 'game' && state.fields?.group_by && state.fields.group_by !== 'item') {
    query.group_by = state.fields.group_by;
    if (state.fields.group) query.group = state.fields.group;
  }

  const ranges = state.ranges || {};
  const rating = ranges.rating || {};
  const min = cleanRatingBound(rating.from);
  const max = cleanRatingBound(rating.to);
  if (min) query.rating_min = min;
  if (max) query.rating_max = max;
  rangeQuery(query, 'date_added', ranges.dateAdded);
  rangeQuery(query, 'release_date', ranges.release);
  rangeQuery(query, 'completed_date', ranges.completed);

  const fields = state.fields || {};
  for (const key of SINGLE_FIELD_PARAMS) {
    const value = String(fields[key] ?? '').trim();
    if (value && value !== 'all') query[key] = value;
  }
  for (const [key, param, modeParam] of MULTI_FIELD_PARAMS) {
    const values = Array.isArray(fields[key]) ? fields[key].filter(Boolean) : [];
    if (!values.length) continue;
    query[param] = values.join(',');
    const mode = (state.modes || {})[key];
    if (['and', 'or', 'not'].includes(mode) && mode !== 'or') query[modeParam] = mode;
  }
  return query;
}

/**
 * The stored preferences (what the web remembers per media type) as filter
 * state: layout, sort and direction. Missing values keep the defaults.
 */
export function filtersFromPreferences(prefs, base = defaultLibraryFilters()) {
  if (!prefs) return base;
  return {
    ...base,
    view: prefs.layout === 'table' ? 'table' : 'grid',
    sort: prefs.sort || base.sort,
    direction: prefs.direction || (prefs.sort ? defaultSortDirection(prefs.sort) : base.direction),
  };
}

/** Parse a saved view's query string back into filter state (inverse of libraryQuery). */
export function filtersFromSavedQuery(queryString, base = defaultLibraryFilters()) {
  const params = {};
  for (const pair of String(queryString || '').split('&')) {
    if (!pair) continue;
    const [rawKey, rawValue = ''] = pair.split('=');
    const key = decodeURIComponent(rawKey.replace(/\+/g, ' '));
    const value = decodeURIComponent(rawValue.replace(/\+/g, ' '));
    params[key] = params[key] ? `${params[key]},${value}` : value;
  }
  const next = {
    ...base,
    ranges: { ...base.ranges },
    fields: { ...base.fields },
    modes: { ...base.modes },
  };
  if (params.status && params.status.toLowerCase() !== 'all') next.statuses = params.status.split(',').filter(Boolean);
  else next.statuses = [];
  if (params.sort) next.sort = params.sort;
  if (params.direction) next.direction = params.direction;
  if (params.layout) next.view = params.layout === 'table' ? 'table' : 'grid';
  if (params.initial) next.initial = params.initial;
  if (params.separate_entries) next.separateEntries = params.separate_entries === '1';
  if (params.group_by) next.fields.group_by = params.group_by;
  if (params.group) next.fields.group = params.group;
  const bound = (name, range) => {
    const within = params[`${range}_within`];
    if (within) return { from: '', to: '', within, unit: params[`${range}_within_unit`] || 'days' };
    return { from: params[`${range}_from`] || '', to: params[`${range}_to`] || '', within: '', unit: 'days' };
  };
  next.ranges.rating = { from: params.rating_min || '', to: params.rating_max || '', within: '', unit: 'days' };
  next.ranges.dateAdded = bound(params, 'date_added');
  next.ranges.release = bound(params, 'release_date');
  next.ranges.completed = bound(params, 'completed_date');
  for (const key of SINGLE_FIELD_PARAMS) if (params[key]) next.fields[key] = params[key];
  for (const [key, param, modeParam] of MULTI_FIELD_PARAMS) {
    if (params[param]) next.fields[key] = params[param].split(',').filter(Boolean);
    if (params[modeParam]) next.modes[key] = params[modeParam];
  }
  return next;
}

export function libraryPath(mediaType) {
  return mediaType ? `/api/v1/media/${encodeURIComponent(mediaType)}/` : '/api/v1/media/';
}

function mediaItemPath(identity) {
  const mediaType = identity?.mediaType;
  const source = identity?.source;
  const mediaId = identity?.mediaId;
  if (!mediaType || !source || !mediaId) return '';
  return `/api/v1/media/${encodeURIComponent(mediaType)}/${encodeURIComponent(source)}/${encodeURIComponent(mediaId)}`;
}

function bulkIds(itemIds) {
  return [...new Set((itemIds || []).map(Number).filter(id => Number.isFinite(id) && id > 0))];
}

export function createRemoteLibraryActions(request) {
  // One request per action, handled by the same server code as the web bulk
  // toolbar; the server's message is the honest outcome.
  function bulk(path, body) {
    return request(path, { method: 'POST', body });
  }

  return {
    mode: 'server',
    load(params = {}) {
      const query = libraryQuery(params);
      const groupedOverview = params.mediaType === 'game' && query.group_by && !query.group;
      return request(groupedOverview ? '/api/v1/library/game-groups/' : libraryPath(params.mediaType), { query });
    },
    loadFilterOptions(params = {}) {
      const query = libraryQuery({ ...params, limit: undefined, offset: undefined });
      delete query.limit;
      delete query.offset;
      delete query.sort;
      delete query.direction;
      return request(`/api/v1/media/${encodeURIComponent(params.mediaType)}/filter-options/`, { query });
    },
    async loadItemIds(params = {}) {
      const query = libraryQuery({ ...params, limit: undefined, offset: undefined });
      delete query.limit;
      delete query.offset;
      const payload = await request(
        `/api/v1/media/${encodeURIComponent(params.mediaType)}/item-ids/`,
        { query },
      );
      return bulkIds(payload?.item_ids);
    },
    loadPreferences(mediaType) {
      return request(`/api/v1/library/preferences/${encodeURIComponent(mediaType)}/`);
    },
    savePreferences(mediaType, patch) {
      return request(`/api/v1/library/preferences/${encodeURIComponent(mediaType)}/`, { method: 'PATCH', body: patch });
    },
    createSavedView({ mediaType, name, filters }) {
      const query = libraryQuery({ mediaType, filters });
      delete query.limit;
      delete query.offset;
      if (filters?.view) query.layout = filters.view;
      return request('/api/v1/library/saved-views/', { method: 'POST', body: { mediaType, name, query } });
    },
    deleteSavedView(id) {
      return request(`/api/v1/library/saved-views/${encodeURIComponent(id)}/`, { method: 'DELETE' });
    },
    async shareView({ mediaType, filters }) {
      const query = libraryQuery({ mediaType, filters });
      delete query.limit;
      delete query.offset;
      const payload = await request('/api/v1/library/share-view/', { method: 'POST', body: { mediaType, query } });
      return payload?.url || '';
    },
    loadTags() {
      return request('/api/v1/tags/');
    },
    async loadLists() {
      return request('/api/v1/lists/', { query: { limit: 200 } });
    },
    update({ identity, values = {} } = {}) {
      const path = mediaItemPath(identity);
      if (!path) {
        return Promise.reject(new Error('This row has no provider identity to update.'));
      }
      const body = {};
      if (values.status !== undefined) body.status = values.status || null;
      if (values.score !== undefined) body.score = values.score === '' ? null : values.score;
      if (values.progress !== undefined) body.progress = values.progress === '' ? null : values.progress;
      if (values.start_date !== undefined) body.start_date = values.start_date || null;
      if (values.end_date !== undefined) body.end_date = values.end_date || null;
      return request(`${path}/`, { method: 'PATCH', body });
    },
    remove({ identity } = {}) {
      const path = mediaItemPath(identity);
      if (!path) {
        return Promise.reject(new Error('This row has no provider identity to delete.'));
      }
      return request(`${path}/`, { method: 'DELETE' });
    },
    bulkStatus(itemIds, status) {
      return bulk('/api/v1/library/bulk/status/', { item_ids: bulkIds(itemIds), status });
    },
    bulkAddToList(itemIds, listId) {
      return bulk('/api/v1/library/bulk/list/', { item_ids: bulkIds(itemIds), list_id: Number(listId) });
    },
    bulkApplyTag(itemIds, tagId, mode) {
      return bulk('/api/v1/library/bulk/tags/', {
        item_ids: bulkIds(itemIds),
        tag_id: Number(tagId),
        action: mode === 'remove' ? 'remove' : 'add',
      });
    },
    bulkAddToCollection(itemIds) {
      return bulk('/api/v1/library/bulk/collection/', { item_ids: bulkIds(itemIds) });
    },
    bulkAddPlays(itemIds, options = {}) {
      return bulk('/api/v1/library/bulk/plays/', { item_ids: bulkIds(itemIds), ...options });
    },
    bulkPlaysStatus(operationId) {
      return request(`/api/v1/library/bulk/plays/${encodeURIComponent(operationId)}/`);
    },
  };
}

export function createLocalLibraryActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    load: local,
    loadFilterOptions: local,
    loadItemIds: async () => [],
    loadPreferences: local,
    savePreferences: local,
    createSavedView: local,
    deleteSavedView: local,
    shareView: local,
    loadTags: local,
    loadLists: local,
    update: local,
    remove: local,
    bulkStatus: local,
    bulkAddToList: local,
    bulkApplyTag: local,
    bulkAddToCollection: local,
    bulkAddPlays: local,
    bulkPlaysStatus: local,
  };
}
