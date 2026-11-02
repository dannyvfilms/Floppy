// Pure helpers that combine the Statistics page's per-media-type numbers when
// several media types are selected. No DOM access, so they can be checked with
// `node src/static/js/stats-media-merge.selfcheck.mjs`.
//
// A selection is an array of media type slugs; an empty array means "All media".
(function (root) {
  const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const DAY_MS = 86400000;
  const ALL_COLOR = "#6366f1";

  // "tv,movie" -> ["tv", "movie"] in dropdown order. "all", empty and unknown
  // values are dropped, so old ?media-type=tv links keep working.
  function parseMediaTypeParam(raw, validValues) {
    const wanted = new Set(String(raw || "").split(",").map((value) => value.trim()));
    return validValues.filter((value) => value !== "all" && wanted.has(value));
  }

  function formatMediaTypeParam(types) {
    return types.join(",");
  }

  function epochDayToIso(day) {
    return new Date(day * DAY_MS).toISOString().slice(0, 10);
  }

  // Same rules as stats_activity.calculate_streak_details (longest wins; on a
  // tie the later one wins; "current" only counts if it reaches the end day).
  function streaksFromDays(daySet, endDay) {
    const days = [...daySet].sort((a, b) => a - b);
    if (!days.length) {
      return { current: 0, longest: 0, longestStart: null, longestEnd: null };
    }
    let longest = 1;
    let longestStart = days[0];
    let longestEnd = days[0];
    let streakStart = days[0];
    let prev = days[0];
    const closeRun = () => {
      const length = prev - streakStart + 1;
      if (length > longest || (length === longest && prev > longestEnd)) {
        longest = length;
        longestStart = streakStart;
        longestEnd = prev;
      }
    };
    for (let i = 1; i < days.length; i++) {
      if (days[i] - prev === 1) {
        prev = days[i];
        continue;
      }
      closeRun();
      streakStart = days[i];
      prev = days[i];
    }
    closeRun();

    let current = 0;
    if (endDay !== null && daySet.has(endDay)) {
      current = 1;
      while (daySet.has(endDay - current)) current += 1;
    }
    return { current, longest, longestStart, longestEnd };
  }

  // Summary cards. One type (or All) returns the server's numbers untouched;
  // several types are rebuilt from the raw per-type pieces.
  function mergeSummary(byType, types) {
    if (!types.length) return byType.all || {};
    if (types.length === 1) return byType[types[0]] || {};
    const parts = types.map((type) => byType[type]).filter(Boolean);
    if (!parts.length) return {};

    let completed = 0;
    let total = 0;
    let totalMinutes = 0;
    let scoreSum = 0;
    let scoreCount = 0;
    const weekday = [0, 0, 0, 0, 0, 0, 0];
    const activeDays = new Set();
    let endDay = null;
    parts.forEach((part) => {
      completed += part.completed || 0;
      total += part.total || 0;
      totalMinutes += part.total_minutes || 0;
      scoreSum += part.score_sum || 0;
      scoreCount += part.score_count || 0;
      (part.weekday_minutes || []).forEach((minutes, i) => { weekday[i] += minutes; });
      (part.active_runs || []).forEach(([start, length]) => {
        for (let i = 0; i < length; i++) activeDays.add(start + i);
      });
      if (part.streak_end_day !== undefined) endDay = part.streak_end_day;
    });

    const weekdayTotal = weekday.reduce((a, b) => a + b, 0);
    let mostActiveDay = null;
    let mostActivePct = 0;
    if (weekdayTotal > 0) {
      const top = weekday.indexOf(Math.max(...weekday));
      mostActiveDay = WEEKDAY_NAMES[top];
      mostActivePct = Math.round((weekday[top] / weekdayTotal) * 100);
    }
    const streaks = streaksFromDays(activeDays, endDay);

    return {
      completed,
      total,
      total_minutes: totalMinutes,
      average_score: scoreCount ? Math.round((scoreSum / scoreCount) * 100) / 100 : null,
      has_score: scoreCount > 0,
      most_active_day: mostActiveDay,
      most_active_day_percentage: mostActivePct,
      current_streak: streaks.current,
      longest_streak: streaks.longest,
      longest_streak_start: streaks.longestStart === null ? null : epochDayToIso(streaks.longestStart),
      longest_streak_end: streaks.longestEnd === null ? null : epochDayToIso(streaks.longestEnd),
    };
  }

  // Per year / month / day tiles. Only types measured in the same unit can be
  // added up (hours with hours); a mix such as movies + books returns {} so
  // the tiles hide instead of showing a meaningless sum.
  function mergeConsumption(byType, types) {
    if (!types.length) return byType.all || {};
    if (types.length === 1) return byType[types[0]] || {};
    const parts = types
      .map((type) => byType[type])
      .filter((part) => part && part.has_data && part.primary);
    if (!parts.length) return {};
    const unit = parts[0].primary.unit;
    if (parts.some((part) => part.primary.unit !== unit)) return {};

    const keys = ["total", "per_year", "per_month", "per_day"];
    const sumMetrics = (metrics) => {
      const summed = { ...metrics[0] };
      keys.forEach((key) => {
        summed[key] = metrics.reduce((sum, metric) => sum + (Number(metric[key]) || 0), 0);
      });
      return summed;
    };
    const secondaries = parts.map((part) => part.secondary);
    const sameSecondary = secondaries.every(
      (metric) => metric && metric.unit === secondaries[0].unit,
    );
    return {
      primary: sumMetrics(parts.map((part) => part.primary)),
      secondary: sameSecondary ? sumMetrics(secondaries) : null,
      bonuses: [],
      has_data: true,
    };
  }

  // Activity rhythm: 7 weekdays x 24 hours of session counts. null = no data.
  function sumMatrices(byType, types) {
    if (!types.length) return byType.all || null;
    const matrices = types.map((type) => byType[type]).filter(Boolean);
    if (!matrices.length) return null;
    return Array.from({ length: 7 }, (_, row) =>
      Array.from({ length: 24 }, (_, col) =>
        matrices.reduce((sum, matrix) => sum + ((matrix[row] && matrix[row][col]) || 0), 0)));
  }

  // Hours by month / weekday / time of day. Every type shares the same labels,
  // so bars add up index by index. null = none of the types has data.
  function mergeSeriesChart(byKey, types) {
    if (!types.length) return byKey.all || null;
    const charts = types
      .map((type) => byKey[type])
      .filter((chart) => chart && chart.labels && chart.labels.length && chart.datasets.length);
    if (!charts.length) return null;
    if (charts.length === 1) return charts[0];
    const allDataset = ((byKey.all || {}).datasets || [])[0] || {};
    const merged = JSON.parse(JSON.stringify(charts[0]));
    merged.datasets[0].background_color = allDataset.background_color || ALL_COLOR;
    merged.datasets[0].data = merged.labels.map((_, i) =>
      Math.round(charts.reduce((sum, chart) => sum + (Number(chart.datasets[0].data[i]) || 0), 0) * 100) / 100);
    return merged;
  }

  root.StatsMediaMerge = {
    parseMediaTypeParam,
    formatMediaTypeParam,
    mergeSummary,
    mergeConsumption,
    sumMatrices,
    mergeSeriesChart,
  };
})(typeof window !== "undefined" ? window : globalThis);
