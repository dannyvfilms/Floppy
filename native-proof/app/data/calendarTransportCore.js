const MEDIA_LABELS = {
  tv: 'TV Show',
  season: 'TV Season',
  movie: 'Movie',
  anime: 'Anime',
  book: 'Book',
  game: 'Game',
  podcast: 'Podcast',
  manga: 'Manga',
  comic: 'Comic',
  boardgame: 'Board Game',
  music: 'Music',
  video: 'Video',
};

const RELEASE_TYPE_LABELS = {
  digital: 'Digital',
  physical: 'Physical',
};

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const WEEKDAY_NAMES = [
  'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
];
const WEEKDAY_HEADERS = {
  monday: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
  sunday: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
};
const SENTINEL = { hour: 11, minute: 59, second: 59 };

export function calendarQuery({ month, year, startDate, endDate } = {}) {
  if (startDate && endDate) {
    return { start_date: startDate, end_date: endDate };
  }
  const query = {};
  if (month) query.month = month;
  if (year) query.year = year;
  return query;
}

export function monthGrid(month, year, weekStart = 'monday') {
  const firstWeekday = weekStart === 'sunday' ? 0 : 1;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const firstDay = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const leading = (firstDay - firstWeekday + 7) % 7;
  const cells = [];
  for (let index = 0; index < leading; index += 1) cells.push(0);
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);
  while (cells.length % 7) cells.push(0);
  const weeks = [];
  for (let index = 0; index < cells.length; index += 7) {
    weeks.push(cells.slice(index, index + 7));
  }
  return { weeks, daysInMonth, days: Array.from({ length: daysInMonth }, (_, i) => i + 1) };
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function localDay(datetime) {
  const value = new Date(datetime);
  if (Number.isNaN(value.getTime())) return null;
  return {
    date: value,
    day: value.getDate(),
    month: value.getMonth() + 1,
    year: value.getFullYear(),
    hours: value.getHours(),
    minutes: value.getMinutes(),
    seconds: value.getSeconds(),
  };
}

function timeLabel(parts, { unknown }) {
  if (unknown) return '';
  const suffix = parts.hours >= 12 ? 'PM' : 'AM';
  const hour = parts.hours % 12 || 12;
  return `at ${hour}:${pad(parts.minutes)} ${suffix}`;
}

function cardLines(item) {
  const lines = [];
  const release = item.release_datetime ? new Date(item.release_datetime) : null;
  if (release && !Number.isNaN(release.getTime())) {
    lines.push(String(release.getUTCFullYear()));
  }
  if (item.runtime_minutes) lines.push(`${item.runtime_minutes} min`);
  if (item.number_of_pages) lines.push(`${item.number_of_pages} pages`);
  return lines;
}

function mediaTypeFor(item) {
  return item.library_media_type || item.media_type || '';
}

export function releaseFromEvent(event) {
  const item = event?.item || {};
  const parts = localDay(event?.datetime);
  const unknownTime = Boolean(
    parts
    && parts.hours === SENTINEL.hour
    && parts.minutes === SENTINEL.minute
    && parts.seconds === SENTINEL.second,
  );
  const mediaType = mediaTypeFor(item);
  const releaseType = event.release_type || '';
  const releaseTypeLabel = RELEASE_TYPE_LABELS[releaseType] || '';
  const seasonNumber = item.season_number;
  const contentNumber = event.content_number != null
    ? event.content_number
    : item.episode_number;
  const episodeLabel = mediaType === 'season'
    && seasonNumber != null
    && contentNumber != null
    ? `S${pad(seasonNumber)}E${pad(contentNumber)}`
    : '';
  const clock = parts ? timeLabel(parts, { unknown: unknownTime }) : '';
  let subtitle = episodeLabel || (releaseTypeLabel ? `${releaseTypeLabel} release` : '');
  if (clock) {
    subtitle = `${subtitle} ${clock}`.trim();
  } else if (!episodeLabel && !releaseTypeLabel) {
    subtitle = 'Time unknown';
  }
  return {
    id: `event-${event.id}`,
    mediaType,
    mediaLabel: MEDIA_LABELS[mediaType] || mediaType,
    releaseType,
    releaseTypeLabel,
    status: '',
    title: item.title || '',
    href: item.url || '',
    image: item.image || null,
    poster: item.image || null,
    episodeLabel,
    eventTime: clock,
    subtitle,
    unknownTime,
    sortTime: parts ? Math.floor(parts.date.getTime() / 1000) : 0,
    cardLines: cardLines(item),
    day: parts?.day ?? null,
    month: parts?.month ?? null,
    year: parts?.year ?? null,
  };
}

export function releasesByDay(results = []) {
  const grouped = {};
  results.forEach(event => {
    const release = releaseFromEvent(event);
    if (!release.day) return;
    const key = String(release.day);
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(release);
  });
  Object.values(grouped).forEach(list => {
    list.sort((left, right) => {
      if (left.unknownTime !== right.unknownTime) return left.unknownTime ? 1 : -1;
      if (!left.unknownTime && left.sortTime !== right.sortTime) {
        return left.sortTime - right.sortTime;
      }
      return String(left.title).localeCompare(String(right.title), undefined, {
        sensitivity: 'base',
        numeric: true,
      });
    });
  });
  return grouped;
}

export function calendarModelFromPayload(payload, { month, year, weekStart = 'monday', today = new Date() } = {}) {
  const results = Array.isArray(payload) ? payload : payload?.results || [];
  const grid = monthGrid(month, year, weekStart);
  const releases = releasesByDay(results);
  const releaseDays = Object.keys(releases)
    .map(Number)
    .sort((left, right) => left - right);
  const isCurrentMonth = today.getMonth() + 1 === month && today.getFullYear() === year;
  const selectedDay = isCurrentMonth
    ? today.getDate()
    : releaseDays[0] || 1;
  return {
    month,
    year,
    monthName: MONTH_NAMES[month - 1],
    weekdayHeaders: WEEKDAY_HEADERS[weekStart] || WEEKDAY_HEADERS.monday,
    weeks: grid.weeks,
    daysInMonth: grid.days,
    dayLabels: Object.fromEntries(
      grid.days.map(day => [String(day), WEEKDAY_NAMES[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]]),
    ),
    today: {
      day: today.getDate(),
      month: today.getMonth() + 1,
      year: today.getFullYear(),
    },
    selectedDay,
    releases,
    total: results.length,
    empty: results.length === 0,
  };
}

export function createRemoteCalendarActions(request) {
  return {
    mode: 'server',
    fetchReleases() {
      return request('/api/v1/calendar/update/', { method: 'POST' });
    },
    read(params = {}) {
      return request('/api/v1/calendar/', { query: calendarQuery(params) });
    },
    async readAll(params = {}) {
      const query = { ...calendarQuery(params), limit: 200, offset: 0 };
      const results = [];
      let total = null;
      for (;;) {
        const page = await request('/api/v1/calendar/', { query });
        results.push(...(page?.results || []));
        if (total == null) {
          const value = Number(page?.pagination?.total);
          total = Number.isFinite(value) ? value : results.length;
        }
        const next = page?.pagination?.next;
        if (!next || results.length >= total) break;
        const offset = /[?&]offset=(\d+)/.exec(next)?.[1];
        if (offset == null) break;
        query.offset = Number(offset);
      }
      return { results, pagination: { total: total ?? results.length } };
    },
  };
}

export function createLocalCalendarActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    fetchReleases: local,
    read: local,
    readAll: local,
  };
}