const MODEL_PATH = '/statistics';
const TALENT_PATH = '/statistics/fragments/talent';
const PREFERENCE_PATHS = {
  compareMode: '/statistics/compare-mode',
  mediaTypes: '/statistics/media-types',
  topTalentSort: '/statistics/top-talent-sort',
  genreSort: '/statistics/genre-sort',
  studioSort: '/statistics/studio-sort',
  refresh: '/statistics/refresh',
};

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

function chartGroup(model, group, mediaTypes) {
  const source = model?.charts?.[group];
  if (!source) return {};
  const selected = Array.isArray(mediaTypes) ? mediaTypes : [];
  if (selected.length === 1) {
    return source.types?.[selected[0]] || source.all || {};
  }
  return source.all || {};
}

export function flattenStatisticsModel(model, mediaTypes = []) {
  const summary = model?.summary || {};
  const selected = Array.isArray(mediaTypes) ? mediaTypes : [];
  const activeSummary = selected.length === 1
    ? summary.types?.[selected[0]] || summary.all || {}
    : summary.all || {};
  const overviews = model?.sections?.overviews || {};
  const overviewItems = selected.length
    ? selected.map(type => overviews[type]).filter(Boolean)
    : Object.values(overviews);
  return {
    summary: activeSummary,
    highlights: selected.length === 1
      ? summary.highlights?.types?.[selected[0]] || summary.highlights?.all || []
      : summary.highlights?.all || [],
    charts: {
      ...chartGroup(model, 'overview', selected),
      ...chartGroup(model, 'heatmap', selected),
      ...chartGroup(model, 'hours', selected),
      ...chartGroup(model, 'status', selected),
      ...chartGroup(model, 'breakdown', selected),
    },
    comparison: model?.sections?.comparison || {},
    overviews: overviewItems,
    updatedLabel: summary.updatedLabel || '',
    scaleMax: summary.scaleMax || 10,
  };
}

// The native feature boundary maps Statistics preferences to the existing
// autosave endpoints. Presentation receives plain models and complete action
// results; credentials, CSRF, base URLs and error handling stay in the request
// adapter behind this contract.
export function createRemoteStatisticsActions(request) {
  return {
    mode: 'server',
    loadModel({ rangeName, startDate, endDate, compareMode } = {}) {
      return request(MODEL_PATH + queryString({
        format: 'json',
        'range_name': rangeName,
        'start-date': startDate,
        'end-date': endDate,
        compare: compareMode,
      }));
    },
    loadTalent({ rangeName, startDate, endDate, compareMode } = {}) {
      return request(TALENT_PATH + queryString({
        format: 'json',
        range_name: rangeName,
        'start-date': startDate,
        'end-date': endDate,
        compare: compareMode,
      }));
    },
    saveCompareMode({ compareMode }) {
      return request(PREFERENCE_PATHS.compareMode, {
        method: 'POST',
        form: { compare_mode: compareMode },
      });
    },
    saveMediaTypes({ mediaTypes = [] }) {
      return request(PREFERENCE_PATHS.mediaTypes, {
        method: 'POST',
        form: { media_types: mediaTypes.join(',') },
      });
    },
    saveTopTalentSort({ sortBy, rangeName, startDate, endDate, mediaType } = {}) {
      return request(PREFERENCE_PATHS.topTalentSort, {
        method: 'POST',
        form: {
          sort_by: sortBy,
          range_name: rangeName,
          start_date: startDate,
          end_date: endDate,
          media_type: mediaType,
        },
      });
    },
    saveGenreSort({ sortBy, rangeName, startDate, endDate, mediaType } = {}) {
      return request(PREFERENCE_PATHS.genreSort, {
        method: 'POST',
        form: {
          sort_by: sortBy,
          range_name: rangeName,
          start_date: startDate,
          end_date: endDate,
          media_type: mediaType,
        },
      });
    },
    saveStudioSort({ sortBy, rangeName, startDate, endDate, mediaType } = {}) {
      return request(PREFERENCE_PATHS.studioSort, {
        method: 'POST',
        form: {
          sort_by: sortBy,
          range_name: rangeName,
          start_date: startDate,
          end_date: endDate,
          media_type: mediaType,
        },
      });
    },
    requestRefresh({ rangeName } = {}) {
      return request(PREFERENCE_PATHS.refresh, {
        method: 'POST',
        form: { range_name: rangeName },
      });
    },
  };
}

export function createLocalStatisticsActions(reason) {
  return {
    mode: 'local',
    reason,
    loadModel: async () => null,
    loadTalent: async () => null,
    saveCompareMode: async () => ({ local: true }),
    saveMediaTypes: async () => ({ local: true }),
    saveTopTalentSort: async () => ({ local: true }),
    saveGenreSort: async () => ({ local: true }),
    saveStudioSort: async () => ({ local: true }),
    requestRefresh: async () => ({ local: true, reason }),
  };
}
