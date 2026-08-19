(function () {
function initStatisticsCharts() {
  if (typeof Chart === "undefined") {
    return;
  }
  Chart.register(ChartDataLabels);

  // Resolved once per chart-init pass so custom HTML tooltips (built via
  // inline styles, not Tailwind classes) follow the current light/dark theme.
  function chartThemeColor(varName, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    return value || fallback;
  }
  var CHART_TOOLTIP_BG = chartThemeColor("--color-panel", "#1f2937");
  var CHART_TOOLTIP_BORDER = chartThemeColor("--color-surface-border", "rgba(255,255,255,0.1)");
  var CHART_TOOLTIP_TEXT = chartThemeColor("--color-text", "#f3f4f6");

  // Destroy charts from a previous visit (their canvases were detached by a
  // boosted body swap) before creating new instances.
  (window.__floppyStatsCharts || []).forEach(function (chart) {
    try {
      chart.destroy();
    } catch (error) {
      console.debug("[stats] failed to destroy stale chart", error);
    }
  });
  window.__floppyStatsCharts = [];

  // Custom external tooltip for bar charts
  function customBarTooltip(context) {
    // External custom tooltip
    let tooltipEl = document.getElementById("chartjs-tooltip");

    // Create element if it doesn't exist
    if (!tooltipEl) {
      tooltipEl = document.createElement("div");
      tooltipEl.id = "chartjs-tooltip";
      document.body.appendChild(tooltipEl);
    }

    // Hide if no tooltip
    const tooltipModel = context.tooltip;
    if (tooltipModel.opacity === 0) {
      tooltipEl.style.opacity = 0;
      return;
    }

    // Set Text
    if (tooltipModel.body) {
      const chart = context.chart;
      const dataIndex = tooltipModel.dataPoints[0].dataIndex;
      const title = tooltipModel.title[0] || "";

      // Format title based on chart type
      let formattedTitle = title;
      if (chart.canvas.id === "scoreStackedChart") {
        const score = parseInt(title);
        const scoreMax =
          (chart.options &&
            chart.options.plugins &&
            chart.options.plugins.scoreScaleMax) ||
          10;
        if (score === scoreMax) {
          formattedTitle = `Score: ${scoreMax}`;
        } else {
          formattedTitle = `Score: ${score}.0-${score}.9`;
        }
      }

      function fmt(v) {
        const n = Number(v) || 0;
        return n.toFixed(1);
      }

      let html = '<div style="font-weight:600;margin-bottom:6px;color:' + CHART_TOOLTIP_TEXT + '">' + formattedTitle + "</div>";
      chart.data.datasets.forEach((dataset) => {
        const raw = Number(dataset.data[dataIndex]) || 0;
        if (raw > 0) {
          const bgColor = dataset.backgroundColor;
          const label = dataset.label || "";
          html +=
            '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">' +
            '<span style="width:10px;height:10px;border-radius:2px;background:' +
            bgColor +
            ';flex-shrink:0"></span>' +
            "<span>" + label + ": " + fmt(raw) + "</span>" +
            "</div>";
        }
      });

      tooltipEl.innerHTML = html;
    }

    // Position and style the tooltip
    const position = context.chart.canvas.getBoundingClientRect();

    // Set tooltip styles
    tooltipEl.style.opacity = 1;
    tooltipEl.style.position = "absolute";
    tooltipEl.style.left =
      position.left + window.scrollX + tooltipModel.caretX + "px";
    tooltipEl.style.top =
      position.top + window.scrollY + tooltipModel.caretY + "px";
    tooltipEl.style.transform = "translate(-50%, -100%)";
    tooltipEl.style.pointerEvents = "none";
  }

  // Common configuration for bar charts
  const barChartConfig = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: {
        stacked: true,
        grid: { color: "rgba(255, 255, 255, 0.1)" },
        ticks: { color: "#D1D5DB" },
      },
      y: {
        stacked: true,
        beginAtZero: true,
        grid: { color: "rgba(255, 255, 255, 0.1)" },
        ticks: { color: "#D1D5DB", precision: 0 },
      },
    },
    plugins: {
      legend: {
        position: "bottom",
        labels: {
          color: "#D1D5DB",
          padding: 20,
          boxWidth: 12,
          boxHeight: 12,
          usePointStyle: true,
          pointStyle: "rectRounded",
          textAlign: "center",
          font: {
            size: 12,
            lineHeight: 0.1,
          },
        },
      },
      tooltip: {
        enabled: false, // Disable default tooltip
        mode: "index",
        external: customBarTooltip,
      },
      // Disable datalabels for bar charts
      datalabels: {
        display: false,
      },
    },
    interaction: {
      mode: "index",
      intersect: false,
    },
  };

  // Helper function to process stacked bar data
  function processBarData(chartData) {
    return {
      labels: chartData.labels,
      datasets: chartData.datasets
        .map((dataset) => ({
          label: dataset.label,
          media_type: dataset.media_type,
          data: dataset.data,
          backgroundColor: dataset.background_color,
          borderColor: "rgba(255, 255, 255, 0.1)",
          borderRadius: 6,
          borderWidth: 1,
        }))
        .filter((dataset) => dataset.data.some((value) => value > 0)),
    };
  }

  // Helper function to safely initialize charts
  function initializeChartIfExists(elementId, chartType, data, options) {
    const element = document.getElementById(elementId);
    if (element) {
      const chart = new Chart(element.getContext("2d"), {
        type: chartType,
        data: data,
        options: options,
      });
      window.__floppyStatsCharts.push(chart);
      return chart;
    }
    return null;
  }

  function initializeSingleSeriesBarChart(canvasId, dataElementId) {
    const dataElement = document.getElementById(dataElementId);
    if (!dataElement) {
      return null;
    }

    const rawData = JSON.parse(dataElement.textContent || "null");
    if (!rawData || !rawData.labels || rawData.labels.length === 0) {
      return null;
    }

    const chartOptions = JSON.parse(JSON.stringify(barChartConfig));
    chartOptions.scales.x.stacked = false;
    chartOptions.scales.y.stacked = false;
    if (chartOptions.plugins && chartOptions.plugins.legend) {
      chartOptions.plugins.legend.display = false;
    }

    return initializeChartIfExists(
      canvasId,
      "bar",
      processBarData(rawData),
      chartOptions,
    );
  }

  // Ensure the copied score chart wrapper matches Activity History height
  function matchScoreCopyHeight() {
    const activityEl = document.getElementById("activityHistory");
    const scoreCopyWrapper = document.getElementById("scoreCopyWrapper");
    const scoreCanvasWrapper = document.getElementById("scoreCopyCanvasWrapper");
    const scoreCanvas = document.getElementById("scoreStackedChartCopy");

    if (!scoreCopyWrapper || !scoreCanvasWrapper) return 0;

    // If Activity History is hidden (stacked view), fall back to a generous baseline height
    const minHeight = 320; // ~2x the default 150px canvas height
    const activityHeight = activityEl
      ? Math.max(activityEl.clientHeight || 0, activityEl.offsetHeight || 0)
      : 0;
    const desiredHeight = Math.max(
      minHeight,
      activityHeight ? Math.round(activityHeight * 2) : 0
    );

    scoreCopyWrapper.style.minHeight = desiredHeight + "px";
    scoreCanvasWrapper.style.minHeight = desiredHeight + "px";
    scoreCanvasWrapper.style.height = desiredHeight + "px";

    // Ensure the canvas element fills its parent (Chart.js may set inline size attributes)
    if (scoreCanvas) {
      scoreCanvas.style.height = "100%";
      scoreCanvas.style.width = "100%";
      scoreCanvas.style.minHeight = desiredHeight + "px";
      scoreCanvas.height = desiredHeight;
    }

    return desiredHeight;
  }

  // Create Score Stacked Bar Chart
  const scoreDistributionElement =
    document.getElementById("score_distribution");
  if (scoreDistributionElement) {
    const scoreData = JSON.parse(scoreDistributionElement.textContent);
    const scoreChartOptions = JSON.parse(JSON.stringify(barChartConfig)); // Deep clone
    const scoreScaleMax = scoreData.scale_max || 10;

    // Add score-specific configurations
    scoreChartOptions.scales.x.title = {
      display: true,
      text: "Score",
      color: "#D1D5DB",
      padding: { top: 10, bottom: 0 },
    };

    scoreChartOptions.scales.y.title = {
      display: true,
      text: "Number of Items",
      color: "#D1D5DB",
      padding: { top: 0, left: 10 },
    };

    scoreChartOptions.plugins.title = {
      display: true,
      text: `Average Score: ${scoreData.average_score} / ${scoreScaleMax} (${scoreData.total_scored
        } ${scoreData.total_scored === 1 ? "item" : "items"})`,
      color: "#D1D5DB",
      padding: { bottom: 10 },
      font: { size: 14 },
    };
    scoreChartOptions.plugins.scoreScaleMax = scoreScaleMax;

    // Ensure tooltip is properly configured for score chart
    scoreChartOptions.plugins.tooltip = {
      enabled: false,
      mode: "index",
      intersect: false,
      external: customBarTooltip,
    };

    // Ensure copy wrapper is sized to match Activity History BEFORE initializing the copy
    matchScoreCopyHeight();

    // Debug: log element presence and sizes to help diagnose blank chart issues
    try {
      const activityEl = document.getElementById("activityHistory");
      const copyWrapper = document.getElementById("scoreCopyWrapper");
      const copyCanvasWrapper = document.getElementById("scoreCopyCanvasWrapper");
      const copyCanvas = document.getElementById("scoreStackedChartCopy");
      console.debug("[stats] activityEl:", !!activityEl, "height:", activityEl ? activityEl.clientHeight : null);
      console.debug("[stats] copyWrapper:", !!copyWrapper, "minHeight:", copyWrapper ? copyWrapper.style.minHeight : null);
      console.debug("[stats] copyCanvasWrapper:", !!copyCanvasWrapper, "height:", copyCanvasWrapper ? copyCanvasWrapper.clientHeight : null);
      console.debug("[stats] copyCanvas:", !!copyCanvas, "clientH/clientW:", copyCanvas ? [copyCanvas.clientHeight, copyCanvas.clientWidth] : null);
    } catch (e) {
      // swallow debug errors
      console.debug("[stats] debug error", e);
    }

    // Prefer a daily-hours dataset for the copy (if provided by backend)
    const dailyHoursEl = document.getElementById("daily_hours_by_media_type");
    if (dailyHoursEl) {
      const dailyData = JSON.parse(dailyHoursEl.textContent || "null");
      if (dailyData && dailyData.labels && dailyData.labels.length > 0 && dailyData.datasets && dailyData.datasets.length > 0) {
        // Determine bucket size based on selected date range
        let startIso = null;
        let endIso = null;
        try {
          const startEl = document.getElementById("stats_start_date");
          const endEl = document.getElementById("stats_end_date");
          startIso = startEl ? JSON.parse(startEl.textContent || '""') : null;
          endIso = endEl ? JSON.parse(endEl.textContent || '""') : null;
        } catch (e) {
          console.debug('[stats] failed to read start/end JSON', e);
        }

        function chooseBucket(startIso, endIso, labels) {
          // Choose a bucket (day/week/month/year) by finding the
          // coarsest granularity that keeps the number of bars
          // reasonably small (target ~36 bars).
          // If start/end ISO are not provided (All Time), try to infer
          // them from the provided labels array (first/last date strings).
          let startIsoLocal = startIso;
          let endIsoLocal = endIso;
          if ((!startIsoLocal || !endIsoLocal) && Array.isArray(labels) && labels.length) {
            startIsoLocal = labels[0];
            endIsoLocal = labels[labels.length - 1];
          }
          if (!startIsoLocal || !endIsoLocal) {
            // If we only have labels and it's a short range, still favor day buckets
            if (labels && labels.length && labels.length <= 45) return 'day';
            return 'month';
          }
          const start = new Date(startIsoLocal);
          const end = new Date(endIsoLocal);
          const msPerDay = 24 * 60 * 60 * 1000;
          const spanDays = Math.ceil((end - start) / msPerDay) + 1;

          const maxBars = 36;

          // If the backend already gave us daily labels and there aren't many,
          // keep the day granularity even if timezone math nudges spanDays upward.
          if (labels && labels.length && labels.length <= 45) return 'day';

          // Day: one label per day
          if (spanDays <= 31) return 'day';

          // Week: one label per ISO week (approx 7 days)
          const spanWeeks = Math.ceil(spanDays / 7);
          if (spanWeeks <= maxBars) return 'week';

          // Month: compute month diff inclusive
          const spanMonths = (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth()) + 1;
          if (spanMonths <= maxBars) return 'month';

          // Otherwise fall back to years
          return 'year';
        }

        function getWeekStartIso(d) {
          const date = parseIsoDateLocal(d);
          // ISO week start: Monday
          const day = date.getDay(); // 0 Sun .. 6 Sat
          const diff = (day + 6) % 7; // days since Monday
          const wk = new Date(date);
          wk.setDate(date.getDate() - diff);
          wk.setHours(0, 0, 0, 0);
          return wk.toISOString().slice(0, 10);
        }

        function getMonthIso(d) {
          const date = parseIsoDateLocal(d);
          const year = date.getFullYear();
          const month = String(date.getMonth() + 1).padStart(2, "0");
          return `${year}-${month}`; // YYYY-MM
        }

        function getYearIso(d) {
          const date = parseIsoDateLocal(d);
          return String(date.getFullYear());
        }

        function parseIsoDateLocal(iso) {
          const parts = iso.split("-");
          const y = Number(parts[0]);
          const m = Number(parts[1]);
          const d = Number(parts[2] || 1);
          return new Date(y, m - 1, d); // Local time, avoids TZ shifting backward
        }

        function formatBucketLabel(bucket, key, startIso, endIso) {
          const nowYear = new Date().getFullYear();
          let startYear = null;
          let endYear = null;
          try {
            if (startIso) startYear = new Date(startIso).getFullYear();
            if (endIso) endYear = new Date(endIso).getFullYear();
          } catch (e) {
            // ignore
          }

          if (bucket === 'day') {
            const d = parseIsoDateLocal(key);
            const opts = { month: 'short', day: 'numeric' };
            // include year if span crosses years or not current year
            if (startYear && endYear && startYear !== endYear) {
              opts.year = 'numeric';
            } else if (d.getFullYear() !== nowYear) {
              opts.year = 'numeric';
            }
            return d.toLocaleDateString(navigator.language || 'en-US', opts);
          }

          if (bucket === 'week') {
            // key is ISO date for week start (YYYY-MM-DD)
            const d = parseIsoDateLocal(key);
            const opts = { month: 'short', day: 'numeric' };
            if (startYear && endYear && startYear !== endYear) {
              opts.year = 'numeric';
            } else if (d.getFullYear() !== nowYear) {
              opts.year = 'numeric';
            }
            // Show a short date for the week (no "Week of" prefix)
            return d.toLocaleDateString(navigator.language || 'en-US', opts);
          }

          if (bucket === 'month') {
            // key is YYYY-MM
            const [yy, mm] = key.split('-');
            const date = new Date(Number(yy), Number(mm) - 1, 1);
            // If the selected range is within the current year, show full month name only
            if (startYear && endYear && startYear === endYear && startYear === nowYear) {
              return date.toLocaleDateString(navigator.language || 'en-US', { month: 'long' });
            }
            // Otherwise show abbreviated month + year
            return date.toLocaleDateString(navigator.language || 'en-US', { month: 'short', year: 'numeric' });
          }

          if (bucket === 'year') {
            return String(key);
          }

          return key;
        }

        function aggregateDailyToBucket(dailyData, bucket) {
          const labels = dailyData.labels || [];

          // If we're using daily buckets, format the labels but keep the data as-is
          if (bucket === 'day') {
            const newLabels = labels.map((k) => formatBucketLabel('day', k, startIso, endIso));
            const newDatasets = dailyData.datasets.map((ds) => ({
              label: ds.label,
              media_type: ds.media_type,
              data: ds.data.map((v) => Number(v) || 0),
              background_color: ds.background_color || ds.backgroundColor || ds.backgroundColor,
            }));

            return { labels: newLabels, datasets: newDatasets };
          }

          const bucketMap = new Map();

          labels.forEach((lbl, idx) => {
            let key;
            if (bucket === 'week') key = getWeekStartIso(lbl);
            else if (bucket === 'month') key = getMonthIso(lbl);
            else if (bucket === 'year') key = getYearIso(lbl);
            else key = lbl;

            if (!bucketMap.has(key)) {
              bucketMap.set(key, Array(dailyData.datasets.length).fill(0));
            }

            dailyData.datasets.forEach((ds, dsIndex) => {
              const value = Number(ds.data[idx]) || 0;
              const arr = bucketMap.get(key);
              arr[dsIndex] = +(arr[dsIndex] + value).toFixed(4);
            });
          });

          const rawKeys = Array.from(bucketMap.keys()).sort();
          const newLabels = rawKeys.map((k) => formatBucketLabel(bucket, k, startIso, endIso));
          const newDatasets = dailyData.datasets.map((ds, i) => ({
            label: ds.label,
            media_type: ds.media_type,
            data: rawKeys.map((k) => bucketMap.get(k)[i] || 0),
            background_color: ds.background_color || ds.backgroundColor || ds.backgroundColor,
          }));

          return { labels: newLabels, datasets: newDatasets };
        }

        const bucket = chooseBucket(startIso, endIso, dailyData.labels);
        const aggregated = aggregateDailyToBucket(dailyData, bucket);
        const dailyOptions = JSON.parse(JSON.stringify(barChartConfig));
        dailyOptions.scales.x.stacked = true;
        dailyOptions.scales.y.stacked = true;
        // Remove x-axis title for the copy chart (we use the page heading instead)
        if (dailyOptions.scales && dailyOptions.scales.x) {
          dailyOptions.scales.x.title = { display: false };
        }
        dailyOptions.scales.y.title = {
          display: true,
          text: "Hours",
          color: "#D1D5DB",
          padding: { top: 0, left: 10 },
        };
        // Don't add an in-chart title for the copy chart; the page heading above
        // already displays "Played Hours by Media Type" in larger type.
        dailyOptions.plugins.tooltip = {
          enabled: false,
          mode: "index",
          intersect: false,
          external: customBarTooltip,
        };

        const dailyChart = initializeChartIfExists(
          "scoreStackedChartCopy",
          "bar",
          processBarData(aggregated),
          dailyOptions
        );

        if (dailyChart && typeof dailyChart.resize === "function") {
          dailyChart.resize();
        }
      }
    } else {
      // Fallback: initialize copy using score distribution data (legacy behavior)
      // Use the score chart options as a base but override title for the copy
      const fallbackOptions = JSON.parse(JSON.stringify(scoreChartOptions));
      fallbackOptions.plugins = fallbackOptions.plugins || {};
      // Don't set an in-chart title for the fallback; the page heading is used

      const scoreCopyChart = initializeChartIfExists(
        "scoreStackedChartCopy",
        "bar",
        processBarData(scoreData),
        fallbackOptions
      );

      if (scoreCopyChart && typeof scoreCopyChart.resize === "function") {
        scoreCopyChart.resize();
      }
    }
  }

  initializeSingleSeriesBarChart(
    "tvEpisodesByYearChart",
    "tv_episodes_by_year"
  );

  initializeSingleSeriesBarChart(
    "animeEpisodesByYearChart",
    "anime_episodes_by_year"
  );

  initializeSingleSeriesBarChart(
    "moviePlaysByYearChart",
    "movie_plays_by_year"
  );
  initializeSingleSeriesBarChart(
    "bookFinishedByYearChart",
    "book_finished_by_year"
  );
  initializeSingleSeriesBarChart(
    "bookReleasedByYearChart",
    "book_released_by_year"
  );
  initializeSingleSeriesBarChart(
    "bookCompletedLengthChart",
    "book_completed_length"
  );
  initializeSingleSeriesBarChart(
    "comicFinishedByYearChart",
    "comic_finished_by_year"
  );
  initializeSingleSeriesBarChart(
    "comicReleasedByYearChart",
    "comic_released_by_year"
  );
  initializeSingleSeriesBarChart(
    "comicCompletedLengthChart",
    "comic_completed_length"
  );
  initializeSingleSeriesBarChart(
    "mangaFinishedByYearChart",
    "manga_finished_by_year"
  );
  initializeSingleSeriesBarChart(
    "mangaReleasedByYearChart",
    "manga_released_by_year"
  );
  initializeSingleSeriesBarChart(
    "mangaCompletedLengthChart",
    "manga_completed_length"
  );
  initializeSingleSeriesBarChart(
    "gameHoursByYearChart",
    "game_hours_by_year"
  );
  initializeSingleSeriesBarChart(
    "gameHoursByMonthChart",
    "game_hours_by_month"
  );
  // Custom initialization for gameDailyAverageChart with band-level game tooltip
  (function initGameDailyAverageChart() {
    const dataEl = document.getElementById("game_daily_average");
    if (!dataEl) return;
    const rawData = JSON.parse(dataEl.textContent || "null");
    if (!rawData || !rawData.labels || rawData.labels.length === 0) return;

    const topGamesByBand = rawData.top_games_per_band || {};

    function gameDailyAverageTooltip(context) {
      let tooltipEl = document.getElementById("chartjs-tooltip");
      if (!tooltipEl) {
        tooltipEl = document.createElement("div");
        tooltipEl.id = "chartjs-tooltip";
        document.body.appendChild(tooltipEl);
      }

      const tooltipModel = context.tooltip;
      if (tooltipModel.opacity === 0) {
        tooltipEl.style.opacity = 0;
        return;
      }

      if (tooltipModel.body) {
        const bandLabel = tooltipModel.title[0] || "";
        const bandGames = topGamesByBand[bandLabel] || [];

        let html = '<div style="font-weight:600;margin-bottom:6px;color:' + CHART_TOOLTIP_TEXT + '">Avg/day: ' + bandLabel + "</div>";
        bandGames.forEach(function (game, idx) {
          html +=
            '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:4px">' +
            '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px">' +
            (idx + 1) +
            ". " +
            (game.title || "Unknown") +
            "</span>" +
            '<span style="font-weight:600;white-space:nowrap">' +
            (game.formatted_daily_average || "") +
            "</span>" +
            "</div>";
        });

        tooltipEl.innerHTML = html;
      }

      const position = context.chart.canvas.getBoundingClientRect();
      tooltipEl.style.opacity = 1;
      tooltipEl.style.position = "absolute";
      tooltipEl.style.left =
        position.left + window.scrollX + tooltipModel.caretX + "px";
      tooltipEl.style.top =
        position.top + window.scrollY + tooltipModel.caretY + "px";
      tooltipEl.style.transform = "translate(-50%, -100%)";
      tooltipEl.style.pointerEvents = "none";
    }

    const chartOptions = JSON.parse(JSON.stringify(barChartConfig));
    chartOptions.scales.x.stacked = false;
    chartOptions.scales.y.stacked = false;
    if (chartOptions.plugins && chartOptions.plugins.legend) {
      chartOptions.plugins.legend.display = false;
    }
    chartOptions.plugins.tooltip = {
      enabled: false,
      mode: "index",
      intersect: false,
      external: gameDailyAverageTooltip,
    };

    initializeChartIfExists(
      "gameDailyAverageChart",
      "bar",
      processBarData(rawData),
      chartOptions
    );
  })();

  // Music consumption charts
  initializeSingleSeriesBarChart(
    "musicPlaysByYearChart",
    "music_plays_by_year"
  );

  // Podcast charts
  initializeSingleSeriesBarChart(
    "podcastPlaysByYearChart",
    "podcast_plays_by_year"
  );

  function getCurrentMediaType() {
    try {
      return new URL(window.location.href).searchParams.get("media-type") || "all";
    } catch (_) {
      return "all";
    }
  }

  // Maps the page's media-type filter slug to the readable label used as a
  // chart "type" key throughout status_distribution / score_distribution /
  // media_type_distribution payloads (e.g. "tv" -> "TV Show").
  const MEDIA_SLUG_TO_LABEL = {
    tv: "TV Show", movie: "Movie", anime: "Anime", music: "Music",
    podcast: "Podcast", book: "Book", comic: "Comic",
    boardgame: "Board Game", game: "Game", manga: "Manga",
  };

  // ─── Activity Rhythm SVG dot matrix ────────────────────────────────────────
  const weekdayHourEl = document.getElementById("weekday_hour_chart_data");
  const rhythmContainer = document.getElementById("activityRhythmContainer");
  if (weekdayHourEl && rhythmContainer) {
    const rhythmData = JSON.parse(weekdayHourEl.textContent || "{}");

    const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const cellSize = 12;
    const cellGap = 4;
    const dotArea = cellSize + cellGap;
    const maxR = cellSize / 2;
    const labelW = 30;
    const labelH = 14;
    const totalW = labelW + 24 * dotArea;
    const totalH = labelH + 7 * dotArea;

    // Number of intensity tiers (tier 0 = empty cell, tiers 1..TIERS = non-zero).
    const TIERS = 6;

    // Tier → dot radius. Empty cells get the smallest dot; non-zero tiers ramp up to maxR.
    function tierRadius(tier) {
      return tier === 0 ? 1.5 : 2 + (tier / TIERS) * (maxR - 2);
    }

    // Tier → fill. Empty cells faint grey; non-zero tiers ramp indigo opacity up.
    function tierFill(tier) {
      if (tier === 0) return "rgba(255,255,255,0.05)";
      const opacity = 0.2 + 0.8 * (tier / TIERS);
      return `rgba(99,102,241,${opacity.toFixed(2)})`;
    }

    function drawRhythmChart(mediaType) {
      const key = mediaType && mediaType !== "all" ? mediaType : "all";
      const matrix = rhythmData[key] || (key !== "all" ? rhythmData["all"] : null);
      if (!matrix) {
        rhythmContainer.innerHTML =
          '<p class="text-sm text-gray-500 text-center py-6">No activity data for this range.</p>';
        return;
      }

      // Quantile bucketing: rank each cell by its percentile within the non-zero values.
      // This is robust to bulk-import outliers (a single huge day can't crush the scale).
      const nonZeroVals = [];
      for (let r = 0; r < 7; r++) {
        for (let c = 0; c < 24; c++) {
          const v = (matrix[r] && matrix[r][c]) || 0;
          if (v > 0) nonZeroVals.push(v);
        }
      }
      nonZeroVals.sort(function (a, b) { return a - b; });

      function tierFor(v) {
        if (v <= 0 || nonZeroVals.length === 0) return 0;
        // index of first value >= v → percentile rank
        let lo = 0;
        let hi = nonZeroVals.length;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (nonZeroVals[mid] < v) lo = mid + 1;
          else hi = mid;
        }
        const pct = lo / nonZeroVals.length;
        return Math.min(TIERS, Math.floor(pct * TIERS) + 1);
      }

      let cells = "";
      for (let r = 0; r < 7; r++) {
        const cy = labelH + r * dotArea + cellSize / 2;
        cells +=
          `<text x="${labelW - 4}" y="${cy + 3.5}" text-anchor="end" ` +
          `font-size="9" fill="#6b7280">${DAY_LABELS[r]}</text>`;
        for (let c = 0; c < 24; c++) {
          const cx = labelW + c * dotArea + cellSize / 2;
          const count = (matrix[r] && matrix[r][c]) || 0;
          const tier = tierFor(count);
          const radius = tierRadius(tier);
          const fill = tierFill(tier);
          const title = count > 0
            ? `<title>${DAY_LABELS[r]} ${c}:00 — ${count} session${count !== 1 ? "s" : ""}</title>`
            : "";
          cells += `<circle cx="${cx}" cy="${cy}" r="${radius.toFixed(1)}" fill="${fill}">${title}</circle>`;
        }
      }

      let hourLabels = "";
      for (const h of [0, 6, 12, 18]) {
        const cx = labelW + h * dotArea + cellSize / 2;
        const lbl = h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`;
        hourLabels +=
          `<text x="${cx}" y="${labelH - 2}" text-anchor="middle" ` +
          `font-size="9" fill="#6b7280">${lbl}</text>`;
      }

      // "Low → High" legend rendered into the header container (top-right).
      const legendEl = document.getElementById("activityRhythmLegend");
      if (legendEl) {
        legendEl.innerHTML =
          '<span style="font-size:9px;color:#6b7280">Low</span>';
        for (let t = 1; t <= TIERS; t++) {
          const r = tierRadius(t);
          const size = (r * 2).toFixed(1) + "px";
          const dot = document.createElement("span");
          dot.style.cssText =
            `display:inline-block;width:${size};height:${size};border-radius:50%;` +
            `background:${tierFill(t)};flex-shrink:0;`;
          legendEl.appendChild(dot);
        }
        legendEl.insertAdjacentHTML(
          "beforeend",
          '<span style="font-size:9px;color:#6b7280">High</span>'
        );
      }

      rhythmContainer.innerHTML =
        `<svg width="100%" viewBox="0 0 ${totalW} ${totalH}" ` +
        `xmlns="http://www.w3.org/2000/svg" style="overflow:visible;display:block">` +
        hourLabels + cells + `</svg>`;
    }

    drawRhythmChart(getCurrentMediaType());
    window.addEventListener("stats-media-type-changed", function () {
      drawRhythmChart(getCurrentMediaType());
    });
  }

  // ─── Combined Plays charts (by_month / by_weekday / by_time_of_day) ────────
  const combinedPlaysEl = document.getElementById("combined_plays_charts");
  if (combinedPlaysEl) {
    let combinedPlaysData = null;
    try {
      combinedPlaysData = JSON.parse(combinedPlaysEl.textContent || "null");
    } catch (_) {
      combinedPlaysData = null;
    }

    const COMBINED_CHART_SPECS = [
      {
        key: "by_month",
        canvasId: "combinedPlaysByMonthChart",
        containerId: "combinedPlaysByMonthContainer",
      },
      {
        key: "by_weekday",
        canvasId: "combinedPlaysByWeekdayChart",
        containerId: "combinedPlaysByWeekdayContainer",
      },
      {
        key: "by_time_of_day",
        canvasId: "combinedPlaysByTimeChart",
        containerId: "combinedPlaysByTimeContainer",
      },
    ];
    const combinedChartInstances = {};

    const COMBINED_PLAYS_MEDIA_TYPES = ["movie", "tv", "anime", "music", "podcast"];
    const COMBINED_PLAYS_TYPE_LABELS = {
      movie: "Movies",
      tv: "TV Shows",
      anime: "Anime",
      music: "Music",
      podcast: "Podcasts",
    };

    function combinedPlaysTooltip(spec) {
      return function (context) {
        let tooltipEl = document.getElementById("combinedPlaysTooltip");
        if (!tooltipEl) {
          tooltipEl = document.createElement("div");
          tooltipEl.id = "combinedPlaysTooltip";
          tooltipEl.style.cssText =
            "position:absolute;z-index:100;pointer-events:none;opacity:0;transition:opacity 0.2s ease;" +
            "background:" + CHART_TOOLTIP_BG + ";border:1px solid " + CHART_TOOLTIP_BORDER + ";border-radius:6px;" +
            "padding:10px 12px;font-size:13px;color:" + CHART_TOOLTIP_TEXT + ";min-width:160px;" +
            "box-shadow:0 4px 12px rgba(0,0,0,0.4);";
          document.body.appendChild(tooltipEl);
        }

        const tooltipModel = context.tooltip;
        if (tooltipModel.opacity === 0) {
          tooltipEl.style.opacity = 0;
          return;
        }

        if (tooltipModel.body) {
          const dataIndex = tooltipModel.dataPoints[0].dataIndex;
          const title = tooltipModel.title[0] || "";
          const byKey = (combinedPlaysData && combinedPlaysData[spec.key]) || {};
          const currentMediaType = getCurrentMediaType();
          const relevantTypes =
            currentMediaType === "all" ? COMBINED_PLAYS_MEDIA_TYPES : [currentMediaType];

          const rows = relevantTypes
            .map(function (type) {
              const typeChart = byKey[type];
              const ds = typeChart && typeChart.datasets && typeChart.datasets[0];
              const value = ds ? Number(ds.data[dataIndex]) || 0 : 0;
              const color = ds ? ds.background_color : "#9ca3af";
              return {
                label: COMBINED_PLAYS_TYPE_LABELS[type] || type,
                value: value,
                color: color,
              };
            })
            .filter(function (row) {
              return row.value > 0;
            })
            .sort(function (a, b) {
              return b.value - a.value;
            });

          function fmtHoursValue(hrs) {
            return (Number(hrs) || 0).toFixed(1) + "h";
          }

          let html = '<div style="font-weight:600;margin-bottom:6px;color:' + CHART_TOOLTIP_TEXT + '">' + title + "</div>";
          rows.forEach(function (row) {
            html +=
              '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">' +
              '<span style="width:10px;height:10px;border-radius:2px;background:' +
              row.color +
              ';flex-shrink:0"></span>' +
              "<span>" + row.label + ": " + fmtHoursValue(row.value) + "</span>" +
              "</div>";
          });

          tooltipEl.innerHTML = html;
        }

        const position = context.chart.canvas.getBoundingClientRect();
        tooltipEl.style.opacity = 1;
        tooltipEl.style.left =
          position.left + window.scrollX + tooltipModel.caretX + "px";
        tooltipEl.style.top =
          position.top + window.scrollY + tooltipModel.caretY + "px";
        tooltipEl.style.transform = "translate(-50%, -100%)";
      };
    }

    function drawCombinedChart(spec, mediaType) {
      const container = document.getElementById(spec.containerId);
      const byKey = (combinedPlaysData && combinedPlaysData[spec.key]) || {};
      const chartData = byKey[mediaType] || byKey.all;

      if (!chartData || !chartData.labels || chartData.labels.length === 0) {
        if (combinedChartInstances[spec.key]) {
          combinedChartInstances[spec.key].destroy();
          combinedChartInstances[spec.key] = null;
        }
        if (container) {
          container.innerHTML =
            '<p class="text-sm text-gray-500 text-center py-8 w-full">No data for this filter.</p>';
        }
        return;
      }

      if (!container.querySelector("canvas")) {
        container.innerHTML = `<canvas id="${spec.canvasId}"></canvas>`;
      }

      const chartOptions = JSON.parse(JSON.stringify(barChartConfig));
      chartOptions.scales.x.stacked = false;
      chartOptions.scales.y.stacked = false;
      chartOptions.scales.x.grid = { display: false };
      chartOptions.scales.y.border = { display: false };
      if (chartOptions.plugins && chartOptions.plugins.legend) {
        chartOptions.plugins.legend.display = false;
      }
      chartOptions.plugins.tooltip = {
        enabled: false,
        mode: "index",
        intersect: false,
        external: combinedPlaysTooltip(spec),
      };
      const processed = processBarData(chartData);

      if (combinedChartInstances[spec.key]) {
        combinedChartInstances[spec.key].data = processed;
        combinedChartInstances[spec.key].update();
      } else {
        const chart = new Chart(
          document.getElementById(spec.canvasId).getContext("2d"),
          { type: "bar", data: processed, options: chartOptions }
        );
        window.__floppyStatsCharts.push(chart);
        combinedChartInstances[spec.key] = chart;
      }
    }

    function drawAllCombinedCharts(mediaType) {
      COMBINED_CHART_SPECS.forEach(function (spec) {
        drawCombinedChart(spec, mediaType);
      });
    }

    if (combinedPlaysData && typeof combinedPlaysData === "object") {
      drawAllCombinedCharts(getCurrentMediaType());
      window.addEventListener("stats-media-type-changed", function () {
        drawAllCombinedCharts(getCurrentMediaType());
      });
    }
  }

  // ─── Time Across Your Worlds doughnut ───────────────────────────────────────
  const timeWorldsCanvas = document.getElementById("timeWorldsChart");
  const timeWorldsLegendEl = document.getElementById("timeWorldsLegend");
  const timeWorldsCenterEl = document.getElementById("timeWorldsCenter");
  const timeWorldsInfoEl = document.getElementById("timeWorldsInfo");
  const distEl = document.getElementById("media_type_distribution");

  if (timeWorldsCanvas && distEl) {
    const fullDistData = JSON.parse(distEl.textContent || "{}");

    // User's Duration Format preference (mirrors stats_utils._format_hours_minutes).
    let durationFormat = "hours_minutes";
    try {
      const dfEl = document.getElementById("stats_duration_format");
      if (dfEl) durationFormat = JSON.parse(dfEl.textContent) || "hours_minutes";
    } catch (_) { /* keep default */ }

    // Format a duration given in hours, respecting the Duration Format preference.
    // maxParts caps how many units are shown (default 2); pass Infinity for tooltips.
    function fmtHours(hrs, maxParts) {
      if (maxParts === undefined) maxParts = 2;
      let minutes = Math.round(hrs * 60);
      if (minutes <= 0) return "0h 0min";
      if (durationFormat === "long_units") {
        if (minutes < 60) return minutes + "min";
        if (minutes < 1440) {
          return Math.floor(minutes / 60) + "h " + (minutes % 60) + "min";
        }
        const MONTH = 43800;
        const DAY = 1440;
        const HOUR = 60;
        const mo = Math.floor(minutes / MONTH);
        let rem = minutes % MONTH;
        const d = Math.floor(rem / DAY);
        rem %= DAY;
        const h = Math.floor(rem / HOUR);
        const m = rem % HOUR;
        const parts = [];
        if (mo) parts.push(mo + "mo");
        if (d) parts.push(d + "d");
        if (h) parts.push(h + "h");
        if (m || !parts.length) parts.push(m + "min");
        return parts.slice(0, maxParts).join(" ");
      }
      return Math.floor(minutes / 60) + "h " + (minutes % 60) + "min";
    }

    // Palette for genre slices (cycles if there are more genres than colors).
    const GENRE_PALETTE = [
      "#6366f1", "#ec4899", "#10b981", "#f59e0b", "#3b82f6",
      "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#a855f7",
      "#06b6d4", "#84cc16",
    ];

    // Genre data keyed by media type slug (minutes-based types only).
    function loadGenreData(slug) {
      try {
        const el = document.getElementById(slug + "_top_genres");
        return el ? JSON.parse(el.textContent || "[]") : [];
      } catch (_) { return []; }
    }

    // Actual (non-overlapping) total hours for a media type, mirroring the
    // fallback used by date-range.js's currentTypeSummary getter. Genre
    // buckets attribute full hours to every genre a title has, so they can't
    // be summed for a "total" — this reads the real total instead.
    function loadTypeTotalHours(slug) {
      try {
        const el = document.getElementById("summary_stats_by_type");
        const all = el ? JSON.parse(el.textContent || "{}") : {};
        const s = all[slug] || all.all || {};
        return (s.total_minutes || 0) / 60;
      } catch (_) { return 0; }
    }
    const GENRE_TYPES = { tv: 1, movie: 1, anime: 1, music: 1, game: 1 };

    // Elements for updating the card header.
    const timeWorldsTitleEl = document.getElementById("timeWorldsTitle");
    const timeWorldsSubtitleEl = document.getElementById("timeWorldsSubtitle");

    let donutChartInstance = null;

    // External HTML tooltip — lives in <body> so it's never clipped by the canvas.
    function getOrCreateTooltipEl() {
      let el = document.getElementById("timeWorldsTooltip");
      if (!el) {
        el = document.createElement("div");
        el.id = "timeWorldsTooltip";
        el.style.cssText =
          "position:fixed;z-index:9999;pointer-events:none;opacity:0;transition:opacity 0.1s;" +
          "background:" + CHART_TOOLTIP_BG + ";border:1px solid " + CHART_TOOLTIP_BORDER + ";border-radius:6px;" +
          "padding:8px 10px;font-size:12px;color:" + CHART_TOOLTIP_TEXT + ";white-space:nowrap;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
        document.body.appendChild(el);
      }
      return el;
    }

    function externalTooltipHandler(context, getTotalHours) {
      const tooltipEl = getOrCreateTooltipEl();
      const tooltip = context.tooltip;

      if (tooltip.opacity === 0) {
        tooltipEl.style.opacity = "0";
        return;
      }

      if (tooltip.dataPoints && tooltip.dataPoints.length) {
        const dp = tooltip.dataPoints[0];
        const label = dp.label || "";
        const hrs = dp.raw;
        const total = getTotalHours();
        const pct = total > 0 ? Math.round((hrs / total) * 100) : 0;
        const color = dp.dataset.backgroundColor[dp.dataIndex];

        tooltipEl.innerHTML =
          '<div style="font-weight:600;margin-bottom:4px;color:' + CHART_TOOLTIP_TEXT + '">' + label + "</div>" +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span style="width:10px;height:10px;border-radius:2px;background:' + color + ';flex-shrink:0"></span>' +
            '<span>' + fmtHours(hrs, Infinity) + " (" + pct + "%)</span>" +
          "</div>";
      }

      const rect = timeWorldsCanvas.getBoundingClientRect();
      const x = rect.left + tooltip.caretX;
      const y = rect.top + tooltip.caretY;

      // Flip left if near right edge of viewport.
      const tipW = tooltipEl.offsetWidth || 160;
      const left = x + 12 + tipW > window.innerWidth ? x - tipW - 12 : x + 12;

      tooltipEl.style.left = left + "px";
      tooltipEl.style.top = (y - 16) + "px";
      tooltipEl.style.opacity = "1";
    }

    function renderDonut(labels, data, colors, getTotalHours) {
      const externalTooltip = function (ctx) { externalTooltipHandler(ctx, getTotalHours); };

      if (donutChartInstance) {
        donutChartInstance.data.labels = labels;
        donutChartInstance.data.datasets[0].data = data;
        donutChartInstance.data.datasets[0].backgroundColor = colors;
        donutChartInstance.options.plugins.tooltip.external = externalTooltip;
        donutChartInstance.update();
      } else {
        donutChartInstance = new Chart(timeWorldsCanvas.getContext("2d"), {
          type: "doughnut",
          data: { labels: labels, datasets: [{ data: data, backgroundColor: colors }] },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: "68%",
            plugins: {
              legend: { display: false },
              datalabels: { display: false },
              tooltip: { enabled: false, external: externalTooltip },
            },
            elements: { arc: { borderWidth: 1, borderColor: "rgba(0,0,0,0.15)" } },
          },
        });
        window.__floppyStatsCharts.push(donutChartInstance);
      }
    }

    function renderLegend(labels, data, colors, totalHours) {
      if (!timeWorldsLegendEl) return;
      timeWorldsLegendEl.innerHTML = "";
      const sortedIndices = labels.map(function (_, i) { return i; })
        .sort(function (a, b) { return data[b] - data[a]; });
      sortedIndices.forEach(function (i) {
        const label = labels[i];
        const hrs = data[i];
        const color = colors[i];
        const pct = totalHours > 0 ? Math.round((hrs / totalHours) * 100) : 0;
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:14px;font-size:11px;line-height:1.3;";
        row.innerHTML =
          '<div style="flex-shrink:0;display:flex;align-items:center;gap:6px;width:74px">' +
            '<span style="flex-shrink:0;width:10px;height:10px;border-radius:2px;background:' + color + '"></span>' +
            '<span style="flex:1;color:#d1d5db;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + label + "</span>" +
          '</div>' +
          '<div style="flex:1;height:5px;border-radius:3px;background:rgba(255,255,255,0.07);overflow:hidden;min-width:40px">' +
            '<div style="height:100%;border-radius:3px;background:' + color + ';width:' + pct + '%"></div>' +
          '</div>' +
          '<span style="flex-shrink:0;width:34px;text-align:center;color:#d1d5db;font-weight:600">' + pct + "%</span>" +
          '<span style="flex-shrink:0;min-width:80px;text-align:center;color:#6b7280;font-variant-numeric:tabular-nums;white-space:nowrap">' + fmtHours(hrs) + "</span>";
        timeWorldsLegendEl.appendChild(row);
      });
    }

    function drawTimeWorldsChart(mediaType) {
      const container = document.getElementById("timeWorldsContainer");
      const isFiltered = mediaType && mediaType !== "all";
      const hasGenres = isFiltered && GENRE_TYPES[mediaType];
      const genres = hasGenres ? loadGenreData(mediaType) : [];

      if (isFiltered && hasGenres && genres.length > 0) {
        // ── Genre mode ──────────────────────────────────────────────────────
        const labels = genres.map(function (g) { return g.name; });
        const data = genres.map(function (g) { return +(g.minutes / 60).toFixed(2); });
        const colors = genres.map(function (_, i) { return GENRE_PALETTE[i % GENRE_PALETTE.length]; });
        const totalHours = loadTypeTotalHours(mediaType);

        if (timeWorldsTitleEl) timeWorldsTitleEl.textContent = "Top Genres";
        if (timeWorldsSubtitleEl) timeWorldsSubtitleEl.textContent = "Where your " + mediaType + " hours go.";
        if (timeWorldsInfoEl) timeWorldsInfoEl.classList.remove("hidden");

        if (timeWorldsCenterEl) {
          timeWorldsCenterEl.innerHTML =
            '<span style="font-size:1rem;font-weight:700;color:' + CHART_TOOLTIP_TEXT + ';line-height:1.2;text-align:center">' +
            fmtHours(totalHours) + "</span>" +
            '<span style="font-size:0.65rem;color:#9ca3af;line-height:1.2">total</span>';
        }

        renderDonut(labels, data, colors, function () { return totalHours; });
        renderLegend(labels, data, colors, totalHours);
        return;
      }

      // ── Type distribution mode (all, or filtered type with no genre data) ─
      if (timeWorldsTitleEl) timeWorldsTitleEl.textContent = "Hours by Media Type";
      if (timeWorldsSubtitleEl) timeWorldsSubtitleEl.textContent = "Where your hours go.";
      if (timeWorldsInfoEl) timeWorldsInfoEl.classList.add("hidden");

      // Build the filtered view of the distribution data.
      let labels, data, colors;
      if (!isFiltered || !fullDistData.labels) {
        labels = fullDistData.labels || [];
        const ds = (fullDistData.datasets || [{}])[0] || {};
        data = ds.data || [];
        colors = ds.backgroundColor || [];
      } else {
        // Single-type filter for a type with no genre breakdown.
        const targetLabel = MEDIA_SLUG_TO_LABEL[mediaType];
        const idx = targetLabel ? (fullDistData.labels || []).indexOf(targetLabel) : -1;
        if (idx >= 0) {
          const ds = fullDistData.datasets[0];
          labels = [fullDistData.labels[idx]];
          data = [ds.data[idx]];
          colors = [ds.backgroundColor[idx]];
        } else {
          labels = []; data = []; colors = [];
        }
      }

      if (!labels.length) {
        if (donutChartInstance) { donutChartInstance.destroy(); donutChartInstance = null; }
        if (container) {
          container.innerHTML =
            '<p class="text-sm text-gray-500 text-center py-8 w-full">No time data available for this filter.</p>';
        }
        return;
      }

      const totalHours = data.reduce(function (a, b) { return a + b; }, 0);

      if (timeWorldsCenterEl) {
        timeWorldsCenterEl.innerHTML =
          '<span style="font-size:1rem;font-weight:700;color:' + CHART_TOOLTIP_TEXT + ';line-height:1.2;text-align:center">' +
          fmtHours(totalHours) + "</span>" +
          '<span style="font-size:0.65rem;color:#9ca3af;line-height:1.2">total</span>';
      }

      renderDonut(labels, data, colors, function () { return totalHours; });
      renderLegend(labels, data, colors, totalHours);
    }

    if (fullDistData.labels && fullDistData.labels.length > 0) {
      drawTimeWorldsChart(getCurrentMediaType());
      window.addEventListener("stats-media-type-changed", function () {
        drawTimeWorldsChart(getCurrentMediaType());
      });
    } else {
      const container = document.getElementById("timeWorldsContainer");
      if (container) {
        container.innerHTML =
          '<p class="text-sm text-gray-500 text-center py-8 w-full">No time data available for this range.</p>';
      }
    }
  }

  // ─── Status Composition donut (status_distribution, aggregated or single-type) ──
  const statusCompositionDataEl = document.getElementById("status_distribution");
  if (statusCompositionDataEl) {
    const statusCompositionData = JSON.parse(statusCompositionDataEl.textContent || "{}");
    let statusCompositionChartInstance = null;

    function getOrCreateStatusCompositionTooltipEl() {
      let el = document.getElementById("statusCompositionTooltip");
      if (!el) {
        el = document.createElement("div");
        el.id = "statusCompositionTooltip";
        el.style.cssText =
          "position:fixed;z-index:9999;pointer-events:none;opacity:0;transition:opacity 0.1s;" +
          "background:" + CHART_TOOLTIP_BG + ";border:1px solid " + CHART_TOOLTIP_BORDER + ";border-radius:6px;" +
          "padding:8px 10px;font-size:12px;color:" + CHART_TOOLTIP_TEXT + ";white-space:nowrap;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
        document.body.appendChild(el);
      }
      return el;
    }

    function statusCompositionTooltipHandler(context, canvas, getTotal) {
      const tooltipEl = getOrCreateStatusCompositionTooltipEl();
      const tooltip = context.tooltip;
      if (tooltip.opacity === 0) {
        tooltipEl.style.opacity = "0";
        return;
      }
      if (tooltip.dataPoints && tooltip.dataPoints.length) {
        const dp = tooltip.dataPoints[0];
        const label = dp.label || "";
        const count = dp.raw;
        const total = getTotal();
        const pct = total > 0 ? Math.round((count / total) * 100) : 0;
        const color = dp.dataset.backgroundColor[dp.dataIndex];
        tooltipEl.innerHTML =
          '<div style="font-weight:600;margin-bottom:4px;color:' + CHART_TOOLTIP_TEXT + '">' + label + "</div>" +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span style="width:10px;height:10px;border-radius:2px;background:' + color + ';flex-shrink:0"></span>' +
            "<span>" + count.toLocaleString() + " (" + pct + "%)</span>" +
          "</div>";
      }
      const rect = canvas.getBoundingClientRect();
      const x = rect.left + tooltip.caretX;
      const y = rect.top + tooltip.caretY;
      const tipW = tooltipEl.offsetWidth || 160;
      const left = x + 12 + tipW > window.innerWidth ? x - tipW - 12 : x + 12;
      tooltipEl.style.left = left + "px";
      tooltipEl.style.top = (y - 16) + "px";
      tooltipEl.style.opacity = "1";
    }

    function renderStatusComposition(canvas, legendEl, centerEl, labels, data, colors) {
      const total = data.reduce(function (a, b) { return a + b; }, 0);
      const externalTooltip = function (ctx) {
        statusCompositionTooltipHandler(ctx, canvas, function () { return total; });
      };

      if (centerEl) {
        centerEl.innerHTML =
          '<span style="font-size:1.1rem;font-weight:700;color:' + CHART_TOOLTIP_TEXT + ';line-height:1.2">' +
          total.toLocaleString() + "</span>" +
          '<span style="font-size:0.65rem;color:#9ca3af;line-height:1.2">total items</span>';
      }

      if (statusCompositionChartInstance) {
        statusCompositionChartInstance.data.labels = labels;
        statusCompositionChartInstance.data.datasets[0].data = data;
        statusCompositionChartInstance.data.datasets[0].backgroundColor = colors;
        statusCompositionChartInstance.options.plugins.tooltip.external = externalTooltip;
        statusCompositionChartInstance.update();
      } else {
        statusCompositionChartInstance = new Chart(canvas.getContext("2d"), {
          type: "doughnut",
          data: { labels: labels, datasets: [{ data: data, backgroundColor: colors }] },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: "68%",
            plugins: {
              legend: { display: false },
              datalabels: { display: false },
              tooltip: { enabled: false, external: externalTooltip },
            },
            elements: { arc: { borderWidth: 1, borderColor: "rgba(0,0,0,0.15)" } },
          },
        });
        window.__floppyStatsCharts.push(statusCompositionChartInstance);
      }

      if (legendEl) {
        legendEl.innerHTML = "";
        const sortedIndices = labels.map(function (_, i) { return i; })
          .sort(function (a, b) { return data[b] - data[a]; });
        sortedIndices.forEach(function (i) {
          const label = labels[i];
          const count = data[i];
          const color = colors[i];
          const pct = total > 0 ? Math.round((count / total) * 100) : 0;
          const row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;gap:10px;font-size:11px;";
          row.innerHTML =
            '<div style="flex-shrink:0;display:flex;align-items:center;gap:6px;min-width:0;width:84px">' +
              '<span style="flex-shrink:0;width:10px;height:10px;border-radius:2px;background:' + color + '"></span>' +
              '<span style="min-width:0;color:#d1d5db;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + label + "</span>" +
            "</div>" +
            '<div style="flex:1;height:5px;border-radius:3px;background:rgba(255,255,255,0.07);overflow:hidden;min-width:40px">' +
              '<div style="height:100%;border-radius:3px;background:' + color + ';width:' + pct + '%"></div>' +
            "</div>" +
            '<span style="flex-shrink:0;width:34px;text-align:center;color:' + CHART_TOOLTIP_TEXT + ';font-weight:700">' + pct + "%</span>" +
            '<span style="flex-shrink:0;min-width:60px;text-align:center;color:#6b7280;font-variant-numeric:tabular-nums">' + count.toLocaleString() + "</span>";
          legendEl.appendChild(row);
        });
      }
    }

    function drawStatusComposition(mediaType) {
      const container = document.getElementById("statusCompositionContainer");
      const subtitleEl = document.getElementById("statusCompositionSubtitle");
      const isFiltered = mediaType && mediaType !== "all";
      const statusLabels = (statusCompositionData.datasets || []).map(function (ds) { return ds.label; });
      const statusColors = (statusCompositionData.datasets || []).map(function (ds) { return ds.background_color; });

      let labels = [];
      let data = [];
      let colors = [];
      let targetLabel = null;

      if (!isFiltered) {
        (statusCompositionData.datasets || []).forEach(function (ds, i) {
          const total = (ds.data || []).reduce(function (a, b) { return a + (Number(b) || 0); }, 0);
          if (total > 0) {
            labels.push(statusLabels[i]);
            data.push(total);
            colors.push(statusColors[i]);
          }
        });
      } else {
        targetLabel = MEDIA_SLUG_TO_LABEL[mediaType];
        const idx = targetLabel ? (statusCompositionData.labels || []).indexOf(targetLabel) : -1;
        if (idx >= 0) {
          (statusCompositionData.datasets || []).forEach(function (ds, i) {
            const value = Number((ds.data || [])[idx]) || 0;
            if (value > 0) {
              labels.push(statusLabels[i]);
              data.push(value);
              colors.push(statusColors[i]);
            }
          });
        }
      }

      if (subtitleEl) {
        subtitleEl.textContent = isFiltered && targetLabel
          ? targetLabel + " status breakdown."
          : "What portion of your library is in each state.";
      }

      if (!labels.length) {
        if (statusCompositionChartInstance) { statusCompositionChartInstance.destroy(); statusCompositionChartInstance = null; }
        if (container) {
          container.innerHTML =
            '<p class="text-sm text-gray-500 text-center py-8 w-full">No status data available for this filter.</p>';
        }
        return;
      }

      if (container && !container.querySelector("canvas")) {
        container.innerHTML =
          '<div class="relative shrink-0" style="width:150px;height:150px;">' +
            '<div id="statusCompositionCenter" class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center"></div>' +
            '<canvas id="statusCompositionChart" style="position:relative;z-index:1"></canvas>' +
          "</div>" +
          '<div id="statusCompositionLegend" class="flex-1 min-w-0 space-y-1.5"></div>';
        statusCompositionChartInstance = null;
      }

      const canvas = document.getElementById("statusCompositionChart");
      const legendEl = document.getElementById("statusCompositionLegend");
      const centerEl = document.getElementById("statusCompositionCenter");
      if (canvas) {
        renderStatusComposition(canvas, legendEl, centerEl, labels, data, colors);
      }
    }

    if (statusCompositionData.labels && statusCompositionData.labels.length > 0) {
      drawStatusComposition(getCurrentMediaType());
      window.addEventListener("stats-media-type-changed", function () {
        drawStatusComposition(getCurrentMediaType());
      });
    } else {
      const container = document.getElementById("statusCompositionContainer");
      if (container) {
        container.innerHTML =
          '<p class="text-sm text-gray-500 text-center py-8 w-full">No status data available for this range.</p>';
      }
    }
  }

  // ─── Rating Distribution (score_distribution, aggregated or single-type) ──
  const ratingDistributionDataEl = document.getElementById("score_distribution");
  if (ratingDistributionDataEl) {
    const ratingDistributionData = JSON.parse(ratingDistributionDataEl.textContent || "{}");
    let ratingDistributionChartInstance = null;

    function buildRatingDistribution(mediaType) {
      const isFiltered = mediaType && mediaType !== "all";
      const labels = ratingDistributionData.labels || [];
      const datasets = ratingDistributionData.datasets || [];
      const data = labels.map(function () { return 0; });
      let totalScored = 0;

      function addDataset(ds) {
        (ds.data || []).forEach(function (v, i) {
          const value = Number(v) || 0;
          data[i] += value;
          totalScored += value;
        });
      }

      let targetLabel = null;
      if (!isFiltered) {
        datasets.forEach(addDataset);
      } else {
        targetLabel = MEDIA_SLUG_TO_LABEL[mediaType];
        const match = datasets.find(function (ds) { return ds.label === targetLabel; });
        if (match) addDataset(match);
      }

      return { labels: labels, data: data, totalScored: totalScored, targetLabel: targetLabel };
    }

    function drawRatingDistribution(mediaType) {
      const container = document.getElementById("ratingDistributionContainer");
      const subtitleEl = document.getElementById("ratingDistributionSubtitle");
      const built = buildRatingDistribution(mediaType);

      if (subtitleEl) {
        const itemsPhrase = built.totalScored.toLocaleString() + " rated" +
          (built.targetLabel ? " " + built.targetLabel : "") + " item" + (built.totalScored === 1 ? "" : "s");
        subtitleEl.textContent = "How your " + itemsPhrase + " are distributed.";
      }

      if (!built.totalScored) {
        if (ratingDistributionChartInstance) { ratingDistributionChartInstance.destroy(); ratingDistributionChartInstance = null; }
        if (container) {
          container.innerHTML =
            '<p class="text-sm text-gray-500 text-center py-8 w-full">No ratings yet for this filter.</p>';
        }
        return;
      }

      if (container && !container.querySelector("canvas")) {
        container.innerHTML = '<canvas id="ratingDistributionChart"></canvas>';
        ratingDistributionChartInstance = null;
      }

      const canvas = document.getElementById("ratingDistributionChart");
      if (!canvas) return;

      const chartOptions = JSON.parse(JSON.stringify(barChartConfig));
      chartOptions.scales.x.stacked = false;
      chartOptions.scales.y.stacked = false;
      chartOptions.scales.x.grid = { display: false };
      chartOptions.scales.y.border = { display: false };
      // Headroom so the top-of-bar count/percentage datalabel never clips
      // against the tallest bar. grace is a percentage of the data range, so
      // it shrinks in pixel terms as the container gets shorter -- pair it
      // with fixed pixel padding that reserves room for the two-line label
      // regardless of container height.
      chartOptions.scales.y.grace = "15%";
      chartOptions.layout = { padding: { top: 26 } };
      if (chartOptions.plugins && chartOptions.plugins.legend) {
        chartOptions.plugins.legend.display = false;
      }
      chartOptions.plugins.datalabels = {
        display: true,
        anchor: "end",
        align: "end",
        color: "#9ca3af",
        font: { size: 10 },
        formatter: function (value) {
          if (!value) return "";
          const pct = built.totalScored > 0 ? ((value / built.totalScored) * 100).toFixed(1) : "0.0";
          return value.toLocaleString() + "\n(" + pct + "%)";
        },
      };
      chartOptions.plugins.tooltip = {
        enabled: false,
        mode: "index",
        intersect: false,
        external: function (context) {
          let tooltipEl = document.getElementById("ratingDistributionTooltip");
          if (!tooltipEl) {
            tooltipEl = document.createElement("div");
            tooltipEl.id = "ratingDistributionTooltip";
            tooltipEl.style.cssText =
              "position:absolute;z-index:100;pointer-events:none;opacity:0;transition:opacity 0.2s ease;" +
              "background:" + CHART_TOOLTIP_BG + ";border:1px solid " + CHART_TOOLTIP_BORDER + ";border-radius:6px;" +
              "padding:8px 10px;font-size:12px;color:" + CHART_TOOLTIP_TEXT + ";box-shadow:0 4px 12px rgba(0,0,0,0.4);";
            document.body.appendChild(tooltipEl);
          }
          const tooltipModel = context.tooltip;
          if (tooltipModel.opacity === 0) {
            tooltipEl.style.opacity = 0;
            return;
          }
          if (tooltipModel.body) {
            const dataIndex = tooltipModel.dataPoints[0].dataIndex;
            const value = built.data[dataIndex] || 0;
            tooltipEl.innerHTML =
              '<div style="font-weight:600;color:' + CHART_TOOLTIP_TEXT + '">Rating ' + built.labels[dataIndex] + "</div>" +
              '<div style="margin-top:4px">' + value.toLocaleString() + (value === 1 ? " item" : " items") + "</div>";
          }
          const position = context.chart.canvas.getBoundingClientRect();
          tooltipEl.style.opacity = 1;
          tooltipEl.style.left = position.left + window.scrollX + tooltipModel.caretX + "px";
          tooltipEl.style.top = position.top + window.scrollY + tooltipModel.caretY + "px";
          tooltipEl.style.transform = "translate(-50%, -100%)";
        },
      };

      const chartData = {
        labels: built.labels,
        datasets: [{
          label: "Items",
          data: built.data,
          backgroundColor: "#6366f1",
          borderColor: "rgba(255, 255, 255, 0.1)",
          borderRadius: 6,
          borderWidth: 1,
        }],
      };

      if (ratingDistributionChartInstance) {
        ratingDistributionChartInstance.data = chartData;
        ratingDistributionChartInstance.options = chartOptions;
        ratingDistributionChartInstance.update();
      } else {
        ratingDistributionChartInstance = new Chart(canvas.getContext("2d"), {
          type: "bar",
          data: chartData,
          options: chartOptions,
        });
        window.__floppyStatsCharts.push(ratingDistributionChartInstance);
      }
    }

    if (ratingDistributionData.labels && ratingDistributionData.labels.length > 0) {
      drawRatingDistribution(getCurrentMediaType());
      window.addEventListener("stats-media-type-changed", function () {
        drawRatingDistribution(getCurrentMediaType());
      });
    } else {
      const container = document.getElementById("ratingDistributionContainer");
      if (container) {
        container.innerHTML =
          '<p class="text-sm text-gray-500 text-center py-8 w-full">No ratings yet.</p>';
      }
    }
  }

  // ─── Status Breakdown (status_distribution, table by media type) ──────────
  const statusBreakdownDataEl = document.getElementById("status_distribution");
  if (statusBreakdownDataEl) {
    const statusBreakdownData = JSON.parse(statusBreakdownDataEl.textContent || "{}");

    // Reverse of MEDIA_SLUG_TO_LABEL (readable label -> slug) so a row's
    // display name can be matched back to its icon/color in MEDIA_TYPE_VISUALS.
    const LABEL_TO_MEDIA_SLUG = {};
    Object.keys(MEDIA_SLUG_TO_LABEL).forEach(function (slug) {
      LABEL_TO_MEDIA_SLUG[MEDIA_SLUG_TO_LABEL[slug]] = slug;
    });

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, function (ch) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
      });
    }

    function drawStatusBreakdown(mediaType) {
      const container = document.getElementById("statusBreakdownContainer");
      const isFiltered = mediaType && mediaType !== "all";
      const targetLabel = isFiltered ? MEDIA_SLUG_TO_LABEL[mediaType] : null;
      const subtitleText = targetLabel
        ? targetLabel + " status counts."
        : "Breakdown by type across all status states.";

      const typeLabels = statusBreakdownData.labels || [];
      let rowIndices = [];
      typeLabels.forEach(function (label, i) {
        if (!isFiltered || label === targetLabel) rowIndices.push(i);
      });

      // Only show status columns that actually have items, mirroring the
      // donut/rating-distribution "hide empty series" convention.
      const statusColumns = (statusBreakdownData.datasets || []).filter(function (ds) {
        return (ds.total || (ds.data || []).reduce(function (a, b) { return a + (Number(b) || 0); }, 0)) > 0;
      });

      if (!rowIndices.length || !statusColumns.length) {
        if (container) {
          container.innerHTML =
            '<p class="text-xs text-gray-400 mb-3">' + escapeHtml(subtitleText) + "</p>" +
            '<p class="text-sm text-gray-500 text-center py-8 w-full">No status data available for this filter.</p>';
        }
        return;
      }

      const totalFor = function (idx) {
        return statusColumns.reduce(function (sum, ds) { return sum + (Number((ds.data || [])[idx]) || 0); }, 0);
      };
      rowIndices = rowIndices.slice().sort(function (a, b) { return totalFor(b) - totalFor(a); });

      const colWidth = function (ds) { return ds.label === "Completed" ? 116 : 84; };

      let html = '<div class="statistics-card-scroll" style="overflow-x:auto;">';
      html += '<div style="min-width:' + (170 + statusColumns.reduce(function (sum, ds) { return sum + colWidth(ds); }, 0) + 56) + 'px;">';

      // Subtitle + column-header row share a single line.
      html += '<div class="flex items-center gap-3 pb-2 mb-1 border-b border-gray-700">';
      html +=
        '<p class="text-xs text-gray-400 flex-1 min-w-0" style="min-width:110px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" ' +
        'id="statusBreakdownSubtitle" title="' + escapeHtml(subtitleText) + '">' + escapeHtml(subtitleText) + "</p>";
      html += '<div class="shrink-0 text-right text-xs font-medium text-gray-400" style="width:56px">Total</div>';
      statusColumns.forEach(function (ds) {
        html +=
          '<div class="shrink-0 text-right text-xs font-medium" style="width:' + colWidth(ds) + 'px;color:' + ds.background_color + '">' +
          escapeHtml(ds.label) + "</div>";
      });
      html += "</div>";

      // Data rows.
      rowIndices.forEach(function (idx) {
        const typeLabel = typeLabels[idx];
        const slug = LABEL_TO_MEDIA_SLUG[typeLabel];
        const visuals = MEDIA_TYPE_VISUALS[slug] || {};
        const total = totalFor(idx);

        html += '<div class="flex items-center gap-3 py-2 border-b border-gray-700/50 last:border-0">';
        html +=
          '<div class="flex items-center gap-2 flex-1 min-w-0" style="min-width:110px">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" ' +
          'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
          'class="w-4 h-4 shrink-0" style="color:' + (visuals.color || "#9ca3af") + '">' + (visuals.icon || "") + "</svg>" +
          '<span class="text-sm text-gray-300 truncate">' + escapeHtml(typeLabel) + "</span>" +
          "</div>";
        html +=
          '<div class="shrink-0 text-sm font-semibold text-white text-right" style="width:56px">' +
          total.toLocaleString() + "</div>";

        statusColumns.forEach(function (ds) {
          const value = Number((ds.data || [])[idx]) || 0;
          if (ds.label === "Completed") {
            const pct = total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;
            html +=
              '<div class="shrink-0 flex items-center gap-2" style="width:' + colWidth(ds) + 'px">' +
              '<div class="rounded-full overflow-hidden shrink-0" style="width:34px;height:4px;background:rgba(255,255,255,0.1)">' +
              '<div style="height:100%;width:' + pct + '%;background:' + ds.background_color + '"></div>' +
              "</div>" +
              '<span class="text-sm text-right flex-1" style="color:' + ds.background_color + '">' + value.toLocaleString() + "</span>" +
              "</div>";
          } else {
            html +=
              '<div class="shrink-0 text-sm text-right" style="width:' + colWidth(ds) + 'px;color:' + ds.background_color + '">' +
              value.toLocaleString() + "</div>";
          }
        });

        html += "</div>";
      });

      html += "</div></div>";

      if (container) container.innerHTML = html;
    }

    if (statusBreakdownData.labels && statusBreakdownData.labels.length > 0) {
      drawStatusBreakdown(getCurrentMediaType());
      window.addEventListener("stats-media-type-changed", function () {
        drawStatusBreakdown(getCurrentMediaType());
      });
    } else {
      const container = document.getElementById("statusBreakdownContainer");
      if (container) {
        container.innerHTML =
          '<p class="text-sm text-gray-500 text-center py-8 w-full">No status data available for this range.</p>';
      }
    }
  }

  // ─── Featured Repeat Player "X% of titles" ring ──────────────────────────
  (function initFeaturedPersonRing() {
    let featuredPersonRingChart = null;
    let featuredPersonRingCanvas = null;

    function readFeaturedPersonPct() {
      const el = document.getElementById("featured_person_pct");
      if (!el) return 0;
      try {
        return Number(JSON.parse(el.textContent || "0")) || 0;
      } catch (_) {
        return 0;
      }
    }

    window.renderFeaturedPersonRing = function (pct) {
      const canvas = document.getElementById("featuredPersonRingChart");
      const centerEl = document.getElementById("featuredPersonRingCenter");
      if (!canvas) {
        if (featuredPersonRingChart) {
          featuredPersonRingChart.destroy();
        }
        featuredPersonRingChart = null;
        featuredPersonRingCanvas = null;
        return;
      }
      const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
      const data = [clamped, Math.max(0, 100 - clamped)];
      const colors = ["#6366f1", "rgba(255,255,255,0.07)"];

      if (centerEl) {
        centerEl.innerHTML =
          '<span style="font-size:1rem;font-weight:700;color:' + CHART_TOOLTIP_TEXT + ';line-height:1.2">' +
          clamped.toFixed(1).replace(/\.0$/, "") + "%</span>" +
          '<span style="font-size:0.6rem;color:#9ca3af;line-height:1.2">of titles</span>';
      }

      if (featuredPersonRingChart && featuredPersonRingCanvas !== canvas) {
        featuredPersonRingChart.destroy();
        featuredPersonRingChart = null;
        featuredPersonRingCanvas = null;
      }

      if (featuredPersonRingChart) {
        featuredPersonRingChart.data.datasets[0].data = data;
        featuredPersonRingChart.data.datasets[0].backgroundColor = colors;
        featuredPersonRingChart.update();
        return;
      }

      featuredPersonRingChart = new Chart(canvas.getContext("2d"), {
        type: "doughnut",
        data: { labels: ["Featured", "Other"], datasets: [{ data: data, backgroundColor: colors }] },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          cutout: "68%",
          plugins: {
            legend: { display: false },
            datalabels: { display: false },
            tooltip: { enabled: false },
          },
          elements: { arc: { borderWidth: 1, borderColor: "rgba(0,0,0,0.15)" } },
        },
      });
      featuredPersonRingCanvas = canvas;
      window.__floppyStatsCharts.push(featuredPersonRingChart);
    };

    if (document.getElementById("featuredPersonRingChart")) {
      window.renderFeaturedPersonRing(readFeaturedPersonPct());
    }
  })();

  window.dispatchEvent(new CustomEvent("stats-charts-initialized"));

  // Initial sizing and on resize for the copied score chart wrapper
  matchScoreCopyHeight();
  // Re-bind through a window-level reference so the resize listener is only
  // attached once but always uses the current page's sizing function.
  window.__floppyStatsFit = matchScoreCopyHeight;
  if (!window.__floppyStatsResizeBound) {
    window.__floppyStatsResizeBound = true;
    window.addEventListener("resize", function () {
      // Debounce-ish
      clearTimeout(window._scoreCopyResizeTimer);
      window._scoreCopyResizeTimer = setTimeout(function () {
        if (window.__floppyStatsFit) {
          window.__floppyStatsFit();
        }
      }, 120);
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initStatisticsCharts, { once: true });
} else {
  // Script was injected after DOM load (e.g. boosted navigation swap).
  initStatisticsCharts();
}
})();
