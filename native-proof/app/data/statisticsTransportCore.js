const OVERVIEW_PATH = '/api/v1/statistics/overview/';
const REFRESH_PATH = '/api/v1/statistics/refresh/';

const PREFERENCES_PATH = '/api/v1/statistics/preferences/';
const TALENT_PATH = '/api/v1/statistics/talent/';
const FEATURED_PERSON_PATH = '/api/v1/statistics/featured-person/';

const READABLE_TYPES = {
  tv: 'TV Show',
  season: 'TV Season',
  episode: 'Episode',
  movie: 'Movie',
  anime: 'Anime',
  manga: 'Manga',
  game: 'Game',
  book: 'Book',
  comic: 'Comic',
  comicissue: 'Comic Issue',
  boardgame: 'Board Game',
  music: 'Music',
  podcast: 'Podcast',
  video: 'Video',
};

const TYPE_LABELS = {
  all: 'titles',
  movie: 'films',
  tv: 'shows',
  game: 'games',
  book: 'books',
  anime: 'titles',
  music: 'albums',
  podcast: 'podcasts',
  comic: 'comics',
  manga: 'manga',
  boardgame: 'board games',
  video: 'videos',
};

const TYPE_FLAVORS = {
  all: 'stories, ideas, and worlds',
  movie: 'film and storytelling',
  tv: 'episodes and seasons',
  game: 'play and adventure',
  book: 'reading and discovery',
  anime: 'anime and storytelling',
  music: 'music and discovery',
  podcast: 'listening and learning',
  comic: 'comics and art',
  manga: 'manga and art',
  boardgame: 'tabletop and strategy',
  video: 'video and motion',
};

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DEFAULT_COLOR = '#6366f1';

function readableType(type) {
  return READABLE_TYPES[type] || type;
}

function numberValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function plural(count, one, many) {
  return numberValue(count) === 1 ? one : many;
}

function playLabel(count) {
  return `${numberValue(count)} ${plural(count, 'play', 'plays')}`;
}

// The statistics payload embeds the IMG_NONE placeholder as an inline SVG data
// URI when no artwork exists; hide it so cards fall back to their own empty art.
function artwork(image) {
  if (typeof image !== 'string' || !image || image.startsWith('data:image')) {
    return '';
  }
  return image;
}

function detailHref(item) {
  const source = item?.source;
  const mediaId = item?.media_id;
  const mediaType = item?.media_type;
  return source && mediaId && mediaType
    ? `/details/${source}/${mediaType}/${mediaId}`
    : '';
}

// Per-type accent colors: the payload does not carry media_type_colors, but the
// score distribution datasets carry the same config colors keyed by readable type.
export function typeColorsFromDistribution(distribution) {
  const colors = {};
  const datasets = Array.isArray(distribution?.datasets) ? distribution.datasets : [];
  datasets.forEach(dataset => {
    if (dataset?.label && dataset.background_color) {
      colors[dataset.label] = dataset.background_color;
    }
  });
  return colors;
}

function typeColor(colors, mediaType) {
  return colors[readableType(mediaType)] || '';
}

// Mirrors stats_activity heat levels via _statistics_level.
function levelFor(count) {
  const thresholds = [0, 3, 6, 9];
  for (let index = 0; index < thresholds.length; index += 1) {
    if (count <= thresholds[index]) return index;
  }
  return 4;
}

function shortDate(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function highlightCard(entry, key, label, prefix) {
  if (!entry || (!entry.title && !entry.item?.title)) return null;
  const playedAt = entry.played_at || '';
  const dateLabel = playedAt ? `${prefix} ${shortDate(playedAt)}` : prefix;
  const mediaType = entry.media_type || entry.item?.media_type || '';
  return {
    key,
    label,
    title: entry.title || entry.item?.title || '',
    meta: mediaType ? readableType(mediaType) : '',
    date: dateLabel,
    image: artwork(entry.image),
    href: detailHref(entry.item),
  };
}

// Mirrors _statistics_highlights_model from the serialized highlight cards.
export function highlightsFromCards(cards) {
  if (!cards || typeof cards !== 'object') return [];
  const list = [
    highlightCard(cards.first_play, 'first', 'First Play', 'Played'),
    highlightCard(cards.last_play, 'last', 'Last Play', 'Played'),
  ];
  const todayCard = cards.today_card || {};
  const today = highlightCard(
    todayCard.entry,
    'today',
    todayCard.label || 'Today',
    todayCard.date_prefix || 'Played in',
  );
  if (today) {
    today.date = `${todayCard.date_prefix || 'Played in'} ${todayCard.year || ''}`.trim();
    list.push(today);
  }
  return list.filter(Boolean);
}

function summaryModel(row, mediaType, comparison = {}) {
  const totalMinutes = numberValue(row?.total_minutes);
  const start = row?.longest_streak_start || '';
  const end = row?.longest_streak_end || '';
  return {
    total: numberValue(row?.total),
    completed: numberValue(row?.completed),
    totalMinutes,
    totalHours: Math.round(totalMinutes / 60),
    totalDays: Math.floor(totalMinutes / 60 / 24),
    averageScore: row?.average_score === null || row?.average_score === undefined
      ? null
      : Math.round(numberValue(row.average_score) * 10) / 10,
    hasScore: Boolean(row?.has_score),
    mostActiveDay: row?.most_active_day || '',
    mostActiveDayLabel: row?.most_active_day || '',
    mostActiveDayPercentage: Math.round(numberValue(row?.most_active_day_percentage)),
    currentStreak: numberValue(row?.current_streak),
    longestStreak: numberValue(row?.longest_streak),
    longestStreakStart: start,
    longestStreakDates: start && end ? (start === end ? start : `${start} - ${end}`) : '',
    typeLabel: TYPE_LABELS[mediaType] || 'titles',
    typeFlavor: TYPE_FLAVORS[mediaType] || 'stories, ideas, and worlds',
    comparison,
  };
}

function heatmapModel(activity, mediaType) {
  const weeks = [];
  const calendarWeeks = Array.isArray(activity?.calendar_weeks) ? activity.calendar_weeks : [];
  calendarWeeks.forEach(week => {
    const days = (Array.isArray(week) ? week : []).map(day => {
      const future = Boolean(day?.future);
      const count = future
        ? 0
        : mediaType
          ? numberValue(day?.by_type?.[mediaType])
          : numberValue(day?.count);
      return {
        key: day?.date,
        count,
        level: future ? 0 : levelFor(count),
        future,
      };
    });
    weeks.push({ days });
  });
  const monthLabels = (Array.isArray(activity?.months) ? activity.months : [])
    .filter(([label]) => label)
    .map(([label, span]) => ({ label, span }));
  return {
    weeks,
    monthLabels,
    weekdayLabels: Array.isArray(activity?.weekday_labels) && activity.weekday_labels.length
      ? activity.weekday_labels
      : WEEKDAY_LABELS,
  };
}

function rhythmModel(weekdayHourData, mediaType) {
  const matrix = (mediaType ? weekdayHourData?.[mediaType] : weekdayHourData?.all) || [];
  return { matrix, weekdayLabels: WEEKDAY_LABELS };
}

function seriesModel(chart, fallbackColor) {
  if (!chart || typeof chart !== 'object') {
    return { labels: [], data: [], color: fallbackColor || DEFAULT_COLOR };
  }
  const datasets = Array.isArray(chart.datasets) ? chart.datasets : [];
  const dataset = datasets[0] || {};
  return {
    labels: Array.isArray(chart.labels) ? chart.labels : [],
    data: Array.isArray(dataset.data) ? dataset.data : [],
    color: dataset.color || dataset.background_color || fallbackColor || DEFAULT_COLOR,
  };
}

function mediaTypeHoursModel(payload, mediaType, colors) {
  if (mediaType) {
    const minutes = numberValue(payload.minutes_per_media_type?.[mediaType]);
    if (minutes <= 0) return { labels: [], data: [], colors: [] };
    return {
      labels: [readableType(mediaType)],
      data: [Math.round((minutes / 60) * 100) / 100],
      colors: [typeColor(colors, mediaType) || DEFAULT_COLOR],
    };
  }
  const distribution = payload.media_type_distribution || {};
  const dataset = (Array.isArray(distribution.datasets) ? distribution.datasets : [])[0] || {};
  return {
    labels: Array.isArray(distribution.labels) ? distribution.labels : [],
    data: Array.isArray(dataset.data) ? dataset.data : [],
    colors: Array.isArray(dataset.backgroundColor) ? dataset.backgroundColor : [],
  };
}

function statusCompositionModel(statusDistribution, mediaType) {
  const result = { labels: [], data: [], colors: [] };
  if (!statusDistribution || typeof statusDistribution !== 'object') return result;
  const typeLabels = Array.isArray(statusDistribution.labels) ? statusDistribution.labels : [];
  let index = null;
  if (mediaType) index = typeLabels.indexOf(readableType(mediaType));
  (Array.isArray(statusDistribution.datasets) ? statusDistribution.datasets : []).forEach(dataset => {
    const values = Array.isArray(dataset?.data) ? dataset.data : [];
    const value = index !== null && index < values.length
      ? numberValue(values[index])
      : values.reduce((sum, value) => sum + numberValue(value), 0);
    if (value > 0) {
      result.labels.push(dataset.label || '');
      result.data.push(value);
      result.colors.push(dataset.background_color || '');
    }
  });
  return result;
}

function ratingDistributionModel(scoreDistribution, mediaType) {
  const labels = Array.isArray(scoreDistribution?.labels) ? scoreDistribution.labels : [];
  const data = new Array(labels.length).fill(0);
  (Array.isArray(scoreDistribution?.datasets) ? scoreDistribution.datasets : []).forEach(dataset => {
    if (mediaType && dataset?.label !== readableType(mediaType)) return;
    (Array.isArray(dataset?.data) ? dataset.data : []).forEach((value, index) => {
      if (index < data.length) data[index] += numberValue(value);
    });
  });
  return {
    labels,
    data: data.map(value => Math.round(value)),
    scaleMax: scoreDistribution?.scale_max || 10,
  };
}

function statusBreakdownModel(statusDistribution, mediaCount, colors, types) {
  const typeLabels = Array.isArray(statusDistribution?.labels) ? statusDistribution.labels : [];
  const rows = [];
  types.forEach(mediaType => {
    const label = readableType(mediaType);
    if (!typeLabels.includes(label)) return;
    const index = typeLabels.indexOf(label);
    const statuses = {};
    (Array.isArray(statusDistribution.datasets) ? statusDistribution.datasets : []).forEach(dataset => {
      const values = Array.isArray(dataset?.data) ? dataset.data : [];
      statuses[dataset.label || ''] = index < values.length ? numberValue(values[index]) : 0;
    });
    rows.push({
      label,
      color: typeColor(colors, mediaType),
      total: numberValue(mediaCount?.[mediaType]),
      statuses,
    });
  });
  const columns = (Array.isArray(statusDistribution?.datasets) ? statusDistribution.datasets : [])
    .map(dataset => ({
      label: dataset?.label || '',
      color: dataset?.background_color || '',
      completed: dataset?.label === 'Completed',
    }));
  return { rows, columns };
}

function completionModel(summaryStats, colors, types) {
  return {
    rows: types.map(mediaType => ({
      label: readableType(mediaType),
      color: typeColor(colors, mediaType),
      completed: numberValue(summaryStats?.[mediaType]?.completed),
      total: numberValue(summaryStats?.[mediaType]?.total),
    })),
  };
}

function chartFamily(payload, mediaType, colors, types) {
  return {
    rhythm: rhythmModel(payload.weekday_hour_chart_data, mediaType),
    mediaTypeHours: mediaTypeHoursModel(payload, mediaType, colors),
    heatmap: heatmapModel(payload.activity_data, mediaType),
    hoursByMonth: seriesModel(
      payload.combined_plays_charts?.by_month?.[mediaType || 'all'],
      mediaType ? typeColor(colors, mediaType) : DEFAULT_COLOR,
    ),
    hoursByWeekday: seriesModel(
      payload.combined_plays_charts?.by_weekday?.[mediaType || 'all'],
      mediaType ? typeColor(colors, mediaType) : DEFAULT_COLOR,
    ),
    hoursByTimeOfDay: seriesModel(
      payload.combined_plays_charts?.by_time_of_day?.[mediaType || 'all'],
      mediaType ? typeColor(colors, mediaType) : DEFAULT_COLOR,
    ),
    statusComposition: statusCompositionModel(payload.status_distribution, mediaType),
    ratingDistribution: ratingDistributionModel(payload.score_distribution, mediaType),
    statusBreakdown: statusBreakdownModel(
      payload.status_distribution,
      payload.media_count,
      colors,
      types,
    ),
    completion: completionModel(payload.summary_stats_by_type, colors, types),
  };
}

function overviewChartModel(key, title, chart, color) {
  const source = chart && typeof chart === 'object' ? chart : {};
  const datasets = Array.isArray(source.datasets) ? source.datasets : [];
  const dataset = datasets[0] || {};
  return {
    key,
    title,
    labels: Array.isArray(source.labels) ? source.labels : [],
    data: Array.isArray(dataset.data) ? dataset.data : [],
    color: dataset.background_color || color,
  };
}

function overviewItem(item) {
  return {
    key: item.key,
    title: item.title || '',
    subtitle: item.subtitle || '',
    value: item.value === undefined || item.value === null ? '' : String(item.value),
    image: artwork(item.image),
    href: item.href || '',
  };
}

function topPlayedPanel(mediaType, topPlayed) {
  const entries = Array.isArray(topPlayed?.[mediaType]) ? topPlayed[mediaType] : [];
  const items = [];
  entries.forEach(entry => {
    const item = entry?.media?.item;
    if (!item) return;
    const duration = entry.formatted_duration || '';
    let subtitle = duration;
    if (mediaType === 'tv' || mediaType === 'anime') {
      subtitle = `${duration} · ${entry.episode_count || 0} ${plural(entry.episode_count, 'episode', 'episodes')}`;
    } else if (mediaType === 'movie') {
      subtitle = `${duration} · ${playLabel(entry.play_count)}`;
    }
    items.push(overviewItem({
      key: `${item.source}:${item.media_id}`,
      title: item.title,
      subtitle,
      image: item.image,
      href: detailHref(item),
    }));
  });
  if (!items.length) return null;
  return { key: `${mediaType}-most-played`, title: 'Most Played', items };
}

function topRatedPanel(mediaType, topRatedByType) {
  const entries = Array.isArray(topRatedByType?.[mediaType]) ? topRatedByType[mediaType] : [];
  const items = [];
  entries.forEach(media => {
    const item = media?.item;
    if (!item) return;
    items.push(overviewItem({
      key: `${item.source}:${item.media_id}`,
      title: item.title,
      value: media.score === null || media.score === undefined ? '' : media.score,
      image: item.image,
      href: detailHref(item),
    }));
  });
  if (!items.length) return null;
  return { key: `${mediaType}-top-rated`, title: 'Top Rated', items };
}

function rowPanel(key, title, rows, buildItem, roundImages = false) {
  const items = (Array.isArray(rows) ? rows : []).map(buildItem).filter(Boolean);
  if (!items.length) return null;
  return { key, title, items, roundImages };
}

function gameOverviewModel(consumption, payload, showYearCharts, color) {
  const chartsObj = consumption.charts || {};
  const charts = [];
  if (showYearCharts) {
    charts.push(overviewChartModel('game-year', 'Game Hours by Year', chartsObj.by_year, color));
  }
  charts.push(overviewChartModel('game-month', 'Game Hours by Month', chartsObj.by_month, color));
  charts.push(overviewChartModel(
    'game-daily-average', 'Average Daily Playtime', chartsObj.by_daily_average, color,
  ));
  const panels = [];
  const mostPlayed = topPlayedPanel('game', payload.top_played);
  if (mostPlayed) panels.push(mostPlayed);
  const platforms = rowPanel(
    'game-platforms',
    'Top Platforms',
    consumption.platform_breakdown,
    platform => overviewItem({
      key: `platform:${platform.name}`,
      title: platform.name,
      subtitle: `${platform.formatted_hours || ''} · ${platform.games || 0} ${plural(platform.games, 'game', 'games')}`,
    }),
  );
  if (platforms) panels.push(platforms);
  return {
    id: 'game',
    typeValue: 'game',
    typeLabel: 'Video Games',
    title: 'Activity Overview',
    charts: charts.filter(chart => chart.labels.length),
    panels,
  };
}

function musicOverviewModel(consumption, showYearCharts, color) {
  const charts = [];
  if (showYearCharts) {
    charts.push(overviewChartModel('music-year', 'Music Plays by Year', consumption.charts?.by_year, color));
  }
  const panel = (key, title, rows, imageKey, roundImages = false) => rowPanel(
    key, title, rows,
    row => overviewItem({
      key: `${key}:${row.id ?? row.name}`,
      title: row.name || row.title || row.label || '',
      subtitle: [
        row.formatted_duration || '',
        row.plays ? playLabel(row.plays) : '',
      ].filter(Boolean).join(' · '),
      image: imageKey ? row[imageKey] : '',
      roundImages,
    }),
    roundImages,
  );
  const panels = [];
  const artists = panel('music-artists', 'Top Artists', consumption.top_artists, 'image', true);
  if (artists) panels.push(artists);
  const albums = panel('music-albums', 'Top Albums', consumption.top_albums, 'image');
  if (albums) panels.push(albums);
  const tracks = panel('music-tracks', 'Top Tracks', consumption.top_tracks, 'album_image');
  if (tracks) panels.push(tracks);
  const decades = panel('music-decades', 'Top Decades', consumption.top_decades, '');
  if (decades) panels.push(decades);
  const countries = panel('music-countries', 'Top Countries', consumption.top_countries, '');
  if (countries) panels.push(countries);
  return {
    id: 'music',
    typeValue: 'music',
    typeLabel: 'Music',
    title: 'Activity Overview',
    charts: charts.filter(chart => chart.labels.length),
    panels,
  };
}

function podcastOverviewModel(consumption, showYearCharts, color) {
  const charts = [];
  if (showYearCharts) {
    charts.push(overviewChartModel('podcast-year', 'Podcast Plays by Year', consumption.charts?.by_year, color));
  }
  const panel = (key, title, rows) => rowPanel(key, title, rows, row => {
    const count = row.plays || 0;
    const duration = row.formatted_duration || '';
    const subtitle = key === 'podcast-longest'
      ? duration
      : [duration, count ? playLabel(count) : ''].filter(Boolean).join(' · ');
    return overviewItem({
      key: `${key}:${row.show_id ?? row.episode_id ?? row.title}`,
      title: row.title || row.show || '',
      subtitle,
      image: row.image,
    });
  });
  const panels = [];
  const mostPlayed = panel('podcast-most-played', 'Most Played', consumption.most_played);
  if (mostPlayed) panels.push(mostPlayed);
  const mostListened = panel('podcast-most-listened', 'Most Listened', consumption.most_listened);
  if (mostListened) panels.push(mostListened);
  const longest = panel('podcast-longest', 'Longest Episodes', consumption.longest_episodes);
  if (longest) panels.push(longest);
  return {
    id: 'podcast',
    typeValue: 'podcast',
    typeLabel: 'Podcasts',
    title: 'Activity Overview',
    charts: charts.filter(chart => chart.labels.length),
    panels,
  };
}

function readingOverviewModel(mediaType, consumption, topRatedByType, showYearCharts, color) {
  const label = readableType(mediaType);
  const unitName = consumption.unit_name || 'Unit';
  const facts = [];
  if (consumption.listening) {
    facts.push({
      key: `${mediaType}-listening`,
      label: 'Listening Time',
      value: consumption.listening.formatted || '',
      copy: 'Audiobook sessions in this range',
    });
  }
  const charts = [];
  if (showYearCharts) {
    charts.push(overviewChartModel(
      `${mediaType}-year`,
      `${consumption.completion_label || 'Completed'} by Year`,
      consumption.completion_charts?.by_year,
      color,
    ));
  }
  charts.push(overviewChartModel(
    `${mediaType}-released`,
    `${label} Released by Year`,
    consumption.release_chart,
    color,
  ));
  charts.push(overviewChartModel(
    `${mediaType}-completed-length`,
    `Completed ${unitName}s`,
    consumption.completed_length_chart,
    color,
  ));
  const panels = [];
  const mostRead = rowPanel(`${mediaType}-most-read`, 'Most Read', consumption.top_items, row => {
    const item = row.media?.item;
    if (!item) return null;
    return overviewItem({
      key: `${item.source}:${item.media_id}`,
      title: item.title,
      subtitle: row.formatted_units || '',
      image: item.image,
      href: detailHref(item),
    });
  });
  if (mostRead) panels.push(mostRead);
  if (mediaType === 'book') {
    const authors = rowPanel(`${mediaType}-authors`, 'Top Authors', consumption.top_authors, author => overviewItem({
      key: `author:${author.name}`,
      title: author.name || '',
      subtitle: `${author.formatted_units || ''} · ${author.titles || 0} ${plural(author.titles, 'book', 'books')}`,
      image: author.image,
    }), true);
    if (authors) panels.push(authors);
  }
  const genreNoun = {
    book: ['book', 'books'],
    comic: ['comic', 'comics'],
    manga: ['manga', 'manga'],
  }[mediaType] || ['title', 'titles'];
  const genres = rowPanel(`${mediaType}-genres`, 'Top Genres', consumption.top_genres, genre => overviewItem({
    key: `genre:${genre.name}`,
    title: genre.name || '',
    subtitle: `${genre.formatted_units || ''} · ${genre.titles || 0} ${plural(genre.titles, genreNoun[0], genreNoun[1])}`,
  }));
  if (genres) panels.push(genres);
  const topRated = topRatedPanel(mediaType, topRatedByType);
  if (topRated) panels.push(topRated);
  return {
    id: mediaType,
    typeValue: mediaType,
    typeLabel: label,
    title: 'Activity Overview',
    facts,
    charts: charts.filter(chart => chart.labels.length),
    panels,
  };
}

// Mirrors _statistics_media_overview_models for the consumption dicts the
// /api/v1 payload serves.
export function overviewsFromPayload(payload, { showYearCharts = false } = {}) {
  const models = {};
  const colors = typeColorsFromDistribution(payload.score_distribution);
  const colorFor = mediaType => typeColor(colors, mediaType) || DEFAULT_COLOR;
  const consumption = payload;
  ['tv', 'anime', 'movie', 'video'].forEach(mediaType => {
    const stats = consumption[`${mediaType}_consumption`] || {};
    if (!stats.has_data) return;
    const charts = [];
    if (showYearCharts) {
      const title = {
        tv: 'Episode Plays by Year',
        anime: 'Episode Plays by Year',
        movie: 'Movie Plays by Year',
        video: 'Video Plays by Year',
      }[mediaType];
      charts.push(overviewChartModel(
        `${mediaType}-year`, title, stats.charts?.by_year, colorFor(mediaType),
      ));
    }
    const panels = [];
    if (mediaType !== 'video') {
      const mostPlayed = topPlayedPanel(mediaType, payload.top_played);
      if (mostPlayed) panels.push(mostPlayed);
      const topRated = topRatedPanel(mediaType, payload.top_rated_by_type);
      if (topRated) panels.push(topRated);
    }
    models[mediaType] = {
      id: mediaType,
      typeValue: mediaType,
      typeLabel: {
        tv: 'TV Shows',
        anime: 'Anime',
        movie: 'Movies',
        video: 'Video',
      }[mediaType],
      title: 'Activity Overview',
      charts: charts.filter(chart => chart.labels.length),
      panels,
    };
  });
  if (consumption.game_consumption?.has_data) {
    models.game = gameOverviewModel(consumption.game_consumption, payload, showYearCharts, colorFor('game'));
  }
  if (consumption.music_consumption?.has_data) {
    models.music = musicOverviewModel(consumption.music_consumption, showYearCharts, colorFor('music'));
  }
  if (consumption.podcast_consumption?.has_data) {
    models.podcast = podcastOverviewModel(consumption.podcast_consumption, showYearCharts, colorFor('podcast'));
  }
  ['book', 'comic', 'manga'].forEach(mediaType => {
    const stats = consumption[`${mediaType}_consumption`] || {};
    if (stats.has_data) {
      models[mediaType] = readingOverviewModel(
        mediaType, stats, payload.top_rated_by_type, showYearCharts, colorFor(mediaType),
      );
    }
  });
  return models;
}

function compactHours(totalMinutes) {
  const minutes = Math.floor(numberValue(totalMinutes));
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h` : `${minutes}m`;
}

// Mirrors get_role_leaders + get_studio_footprint from the top_talent payload.
export function talentFromTopTalent(topTalent, { roleSort = 'plays', studioSort = 'plays' } = {}) {
  const bySort = topTalent?.by_sort || {};
  const selectedSort = bySort[roleSort] ? roleSort : 'plays';
  const bucket = bySort[selectedSort] || {};
  const columns = [];
  [
    ['top_actors', 'actors', 'Actors'],
    ['top_actresses', 'actresses', 'Actresses'],
    ['top_directors', 'directors', 'Directors'],
    ['top_writers', 'writers', 'Writers'],
  ].forEach(([key, bucketName, label]) => {
    const entries = (Array.isArray(bucket[key]) ? bucket[key] : []).map((entry, index) => ({
      name: entry?.name || '',
      source: entry?.source || '',
      personId: String(entry?.person_id ?? ''),
      rank: index + 1,
      plays: numberValue(entry?.plays),
      titles: numberValue(entry?.unique_titles),
      time: entry?.watched_time || '',
      displayMetric: selectedSort === 'time'
        ? compactHours(entry?.watched_minutes)
        : selectedSort === 'titles'
          ? String(numberValue(entry?.unique_titles))
          : String(numberValue(entry?.plays)),
    }));
    if (entries.length) columns.push({ bucket: bucketName, label, entries });
  });

  const studioSortSelected = studioSort === 'time' ? 'time' : 'plays';
  const studioRows = Array.isArray(bySort[studioSortSelected]?.top_studios)
    ? bySort[studioSortSelected].top_studios
    : [];
  const metricKey = studioSortSelected === 'time' ? 'watched_minutes' : 'plays';
  const totalMetric = studioRows.reduce(
    (sum, studio) => sum + numberValue(studio?.[metricKey]), 0,
  ) || 1;
  const studios = studioRows.map((studio, index) => ({
    name: studio?.name || '',
    pct: Math.round((numberValue(studio?.[metricKey]) / totalMetric) * 1000) / 10,
    plays: numberValue(studio?.plays),
    time: studio?.watched_time || '',
    metricLabel: studioSortSelected === 'time'
      ? (studio?.watched_time || '')
      : playLabel(studio?.plays),
    color: DEFAULT_COLOR,
    rank: index + 1,
  }));

  return {
    roleLeaders: {
      title: 'Role Leaders',
      copy: 'The actors, directors and writers you return to most.',
      selected: selectedSort,
      sortOptions: [
        { value: 'plays', label: 'Plays' },
        { value: 'time', label: 'Time' },
        { value: 'titles', label: 'Titles' },
      ],
      columns,
    },
    studioFootprint: {
      title: 'Studio Footprint',
      copy: 'Studios that appear most often.',
      selected: studioSortSelected,
      sortOptions: [
        { value: 'plays', label: 'Plays' },
        { value: 'time', label: 'Time' },
      ],
      studios,
    },
    // Taste signals (genres, era spotlight) are only served by the session
    // talent fragment, not by /api/v1/statistics/overview; the section renders
    // its own empty copy until an API payload carries them. sortOptions is
    // empty so no dead sort menu renders.
    tasteSignals: { sortOptions: [] },
  };
}

// The server decides which media types the filter may offer; the summary keys
// are only the fallback for an older server.
function mediaTypeOptions(summaryStats, available) {
  const types = Array.isArray(available) && available.length
    ? available
    : Object.keys(summaryStats || {}).filter(key => key !== 'all');
  return types.map(type => ({ value: type, label: readableType(type) }));
}

// The Compare-to section: the server returns options, labels and per-type
// deltas; only row colours are added here from the chart palette.
function comparisonModel(comparison, colors) {
  if (!comparison || !Array.isArray(comparison.rows)) return {};
  return {
    title: comparison.title,
    copy: comparison.copy,
    selected: comparison.selected,
    options: comparison.options || [],
    rangeLabel: comparison.rangeLabel || '',
    rows: comparison.rows.map(row => ({ ...row, color: typeColor(colors, row.type) || undefined })),
  };
}

function summaryComparison(comparison, mediaType) {
  if (!comparison) return {};
  if (!mediaType) return comparison.total || {};
  const row = (comparison.rows || []).find(item => item.type === mediaType);
  return row
    ? { label: row.deltaLabel || '', state: row.state, periodLabel: comparison.total?.periodLabel || '', details: '' }
    : {};
}

// The talent endpoint returns the web section's own models: role leaders,
// studios and taste signals, plus the featured repeat player.
export function talentFromPayload(payload) {
  const talent = payload?.talent;
  if (!talent || typeof talent !== 'object') return null;
  return {
    ...talent,
    studioFootprint: talent.studioFootprint
      ? {
        ...talent.studioFootprint,
        studios: (talent.studioFootprint.studios || []).map(studio => ({ ...studio, color: undefined })),
      }
      : talent.studioFootprint,
  };
}

export function featuredFromPerson(person) {
  if (!person || typeof person !== 'object') return null;
  const image = String(person.image || '');
  return {
    name: person.name || '',
    image: image && !/none\.svg$/.test(image) ? image : '',
    uniqueTitles: numberValue(person.unique_titles),
    uniqueMovies: numberValue(person.unique_movies),
    uniqueGames: numberValue(person.unique_games),
    uniqueShows: numberValue(person.unique_shows),
    pctOfLibrary: numberValue(person.pct_of_library),
    knownFor: (person.known_for_pills || []).map(pill => ({ label: pill.label })),
    source: person.source || '',
    personId: String(person.person_id ?? ''),
  };
}

// Map the /api/v1/statistics/overview payload into the shared StatisticsView
// models, mirroring the server's own _build_statistics_react_props. Only data
// the payload carries is mapped; comparison and taste sections have no payload
// source and stay empty.
export function statisticsModelFromPayload(payload, selectedTypes = [], options = {}) {
  const stats = payload?.statistics || payload || {};
  const selected = Array.isArray(selectedTypes) ? selectedTypes : [];
  const summaryStats = stats.summary_stats_by_type || {};
  const colors = typeColorsFromDistribution(stats.score_distribution);
  const distributionLabels = Array.isArray(stats.media_type_distribution?.labels)
    ? stats.media_type_distribution.labels
    : [];
  const allTypes = Object.keys(summaryStats).filter(key => key !== 'all');
  const chartTypes = allTypes.filter(type => distributionLabels.includes(readableType(type)));

  const mediaType = selected.length === 1 ? selected[0] : null;
  const activeSummary = mediaType
    ? summaryStats[mediaType] || summaryStats.all || {}
    : summaryStats.all || {};
  const highlightsByType = stats.history_highlights_by_type || {};
  const activeHighlights = mediaType
    ? (highlightsByType[mediaType] || stats.history_highlights || {})
    : (stats.history_highlights || {});
  const types = mediaType ? [mediaType] : (chartTypes.length ? chartTypes : allTypes);

  const overviewsByType = overviewsFromPayload(stats, {
    showYearCharts: !payload?.range?.range_name || payload?.range?.range_name === 'All Time',
  });
  const overviewItems = selected.length
    ? selected.map(type => overviewsByType[type]).filter(Boolean)
    : Object.values(overviewsByType);

  return {
    summary: summaryModel(activeSummary, mediaType || 'all', summaryComparison(payload?.comparison, mediaType)),
    highlights: highlightsFromCards(activeHighlights),
    charts: chartFamily(stats, mediaType, colors, types),
    comparison: comparisonModel(payload?.comparison, colors),
    overviews: overviewItems,
    talent: talentFromTopTalent(stats.top_talent, {
      roleSort: options.roleSort,
      studioSort: options.studioSort,
    }),
    mediaTypeOptions: mediaTypeOptions(summaryStats, payload?.media_types?.available),
    selectedMediaTypes: payload?.media_types?.selected || null,
    building: Boolean(payload?.building),
    scaleMax: stats.score_distribution?.scale_max || 10,
    rangeName: payload?.range?.range_name || '',
    range: {
      name: payload?.range?.range_name || '',
      startDate: String(payload?.range?.start_date || '').slice(0, 10),
      endDate: String(payload?.range?.end_date || '').slice(0, 10),
      label: payload?.range?.label || '',
    },
  };
}

// The native feature boundary calls the scoped statistics endpoints through the
// authenticated session facade. Presentation receives plain models and complete
// action results; credentials, CSRF, base URLs and error handling stay in the
// request adapter behind this contract.
export function createRemoteStatisticsActions(request) {
  const patchPreferences = body => request(PREFERENCES_PATH, { method: 'PATCH', body });
  const rangeQuery = ({ rangeName, startDate, endDate, compare } = {}) => ({
    range_name: rangeName,
    start_date: rangeName ? undefined : startDate,
    end_date: rangeName ? undefined : endDate,
    compare,
  });
  return {
    mode: 'server',
    // With no range the server answers with the account's default range.
    loadModel(range = {}) {
      return request(OVERVIEW_PATH + queryString(rangeQuery(range)));
    },
    loadTalent(range = {}) {
      return request(TALENT_PATH + queryString(rangeQuery(range)));
    },
    loadPreferences() {
      return request(PREFERENCES_PATH);
    },
    saveDisplayPreferences(values = {}) {
      return patchPreferences(values);
    },
    saveMediaTypes({ mediaTypes = [] }) {
      return patchPreferences({ media_types: mediaTypes });
    },
    saveCompareMode({ compareMode }) {
      return patchPreferences({ compare_mode: compareMode });
    },
    saveDefaultRange({ rangeName }) {
      return patchPreferences({ default_range: rangeName });
    },
    saveTopTalentSort({ sortBy }) {
      return patchPreferences({ top_talent_sort_by: sortBy });
    },
    saveStudioSort({ sortBy }) {
      return patchPreferences({ studio_sort_by: sortBy });
    },
    saveGenreSort({ sortBy }) {
      return patchPreferences({ genre_sort_by: sortBy });
    },
    selectFeaturedPerson({ source, personId, rangeName, startDate, endDate, sortBy } = {}) {
      return request(FEATURED_PERSON_PATH, {
        method: 'POST',
        body: {
          person_source: source,
          person_id: personId,
          sort_by: sortBy,
          ...(rangeName ? { range_name: rangeName } : { start_date: startDate, end_date: endDate }),
        },
      });
    },
    requestRefresh({ rangeName } = {}) {
      return request(REFRESH_PATH, {
        method: 'POST',
        form: { range_name: rangeName },
      });
    },
  };
}

function queryString(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, value);
    }
  });
  const value = search.toString();
  return value ? `?${value}` : '';
}

export function createLocalStatisticsActions(reason) {
  return {
    mode: 'local',
    reason,
    loadModel: async () => null,
    loadTalent: async () => null,
    loadPreferences: async () => null,
    saveMediaTypes: async () => ({ local: true }),
    saveCompareMode: async () => ({ local: true }),
    saveDefaultRange: async () => ({ local: true }),
    saveTopTalentSort: async () => ({ local: true }),
    saveStudioSort: async () => ({ local: true }),
    saveGenreSort: async () => ({ local: true }),
    selectFeaturedPerson: async () => ({ local: true }),
    requestRefresh: async () => ({ local: true, reason }),
  };
}
