// Mirrors app/config.py's MEDIA_TYPE_CONFIG stats_color + svg_icon fields so
// the Average Rating card's icons match the rest of the app without a round
// trip to the server for markup that's identical across every user.
const MEDIA_TYPE_VISUALS = {
  tv: {
    color: "#10b981",
    icon: '<rect width="20" height="15" x="2" y="7" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/>',
  },
  movie: {
    color: "#f97316",
    icon: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
  },
  anime: {
    color: "#3b82f6",
    icon: '<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>',
  },
  manga: {
    color: "#ef4444",
    icon: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  },
  game: {
    color: "#eab308",
    icon: '<line x1="6" x2="10" y1="11" y2="11"/><line x1="8" x2="8" y1="9" y2="13"/><line x1="15" x2="15.01" y1="12" y2="12"/><line x1="18" x2="18.01" y1="10" y2="10"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.649 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/>',
  },
  boardgame: {
    color: "#84cc16",
    icon: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="8" cy="8" r="2"/><path d="M16 8h-2"/><circle cx="16" cy="16" r="2"/><path d="M8 16v-2"/>',
  },
  book: {
    color: "#d946ef",
    icon: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  },
  comic: {
    color: "#06b6d4",
    icon: '<rect width="8" height="18" x="3" y="3" rx="1"/><path d="M7 3v18"/><path d="M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z"/>',
  },
  music: {
    color: "#fb7185",
    icon: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  },
  podcast: {
    color: "#a855f7",
    icon: '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="23"/><line x1="8" x2="16" y1="23" y2="23"/>',
  },
};

// Icon shapes for the combined "Consumption" card's primary/secondary metrics,
// rendered via x-html the same way MEDIA_TYPE_VISUALS.icon is above.
const CONSUMPTION_ICON_PATHS = {
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  gamepad: '<line x1="6" x2="10" y1="11" y2="11"/><line x1="8" x2="8" y1="9" y2="13"/><line x1="15" x2="15.01" y1="12" y2="12"/><line x1="18" x2="18.01" y1="10" y2="10"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.649 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/>',
  "book-open": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  checkmark: '<path d="M20 6 9 17l-5-5"/>',
};

function dateRangePicker(options = {}) {
  const {
    initialRangeName = "",
    initialStartDate = "",
    initialEndDate = "",
    initialCompareMode = "previous_period",
    initialMediaTypeOptions = [],
    refreshUrl = "",
    compareModeUpdateUrl = "",
    csrfToken = "",
    ratingScaleMax = 10,
  } = options;

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const defaultStartDate = new Date(today);
  defaultStartDate.setFullYear(defaultStartDate.getFullYear() - 1);

  const predefinedRanges = [
    { name: "Today", displayName: "Today" },
    { name: "Yesterday", displayName: "Yesterday" },
    { name: "This Week", displayName: "This week" },
    { name: "Last 7 Days", displayName: "Last 7 days" },
    { name: "This Month", displayName: "Month to date" },
    { name: "Last 30 Days", displayName: "Last 30 days" },
    { name: "Last 90 Days", displayName: "Last 90 days" },
    { name: "This Year", displayName: "Year to date" },
    { name: "Last 6 Months", displayName: "Last 6 months" },
    { name: "Last 12 Months", displayName: "Last 12 months" },
    { name: "All Time", displayName: "All time" },
  ];

  const comparisonOptions = [
    { value: "previous_period", label: "Previous period" },
    { value: "last_year", label: "Last year" },
    { value: "none", label: "No comparison" },
  ];

  return {
    isRangeOpen: false,
    isCompareOpen: false,
    isMediaTypeOpen: false,
    activeTab: "predefined",
    selectedRange: initialRangeName || "Last 12 Months",
    startDate: initialStartDate || formatDateForInput(defaultStartDate),
    endDate: initialEndDate || formatDateForInput(today),
    customRangeLabel: "",
    compareMode: initialCompareMode,
    selectedMediaType: "all",
    mediaTypeOptions: initialMediaTypeOptions,
    ratingScaleMax: ratingScaleMax,
    summaryStatsByType: {},
    consumptionStatsByType: {},
    refreshing: false,
    predefinedRanges,
    comparisonOptions,

    get currentTypeSummary() {
      const key = this.summaryStatsByType[this.selectedMediaType]
        ? this.selectedMediaType
        : "all";
      const s = this.summaryStatsByType[key] || {};
      const start = s.longest_streak_start;
      const end = s.longest_streak_end;
      let dates = "";
      if (start) {
        const fmt = (iso) => {
          const [y, m, d] = iso.split("-").map(Number);
          const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
          return `${months[m - 1]} ${d}, ${y}`;
        };
        dates = start === end ? fmt(start) : `${fmt(start)} – ${fmt(end)}`;
      }
      const totalMinutes = s.total_minutes || 0;
      const totalHours = Math.round(totalMinutes / 60);
      const totalDays = Math.floor(totalMinutes / 60 / 24);
      return { ...s, longest_streak_dates_display: dates, total_hours: totalHours, total_days: totalDays };
    },

    get currentConsumption() {
      return this.consumptionStatsByType[this.selectedMediaType] || {};
    },

    fmt(value, decimals) {
      return Number(value ?? 0).toFixed(decimals);
    },

    consumptionIconPath(metric) {
      return metric ? CONSUMPTION_ICON_PATHS[metric.icon] || "" : "";
    },

    consumptionUnitAbbr(unit) {
      return unit === "Hours" ? "hrs" : unit;
    },

    consumptionTiles() {
      const c = this.currentConsumption;
      if (!c || !c.primary) return [];
      const primary = c.primary;
      const secondary = c.secondary;
      const buckets = [
        { key: "year", label: "Per Year", field: "per_year" },
        { key: "month", label: "Per Month", field: "per_month" },
        { key: "day", label: "Per Day", field: "per_day" },
      ];
      const tiles = buckets.map((b) => ({
        key: b.key,
        icon: primary.icon,
        bg: "bg-indigo-600/20",
        color: "text-indigo-400",
        label: b.label,
        value: this.fmt(primary[b.field], 1) + " " + this.consumptionUnitAbbr(primary.unit),
        caption: secondary ? this.fmt(secondary[b.field], 1) + " " + secondary.unit : "",
      }));
      (c.bonuses || []).forEach((bonus, i) => {
        tiles.push(this.consumptionBonusTile(bonus, i));
      });
      return tiles;
    },

    consumptionBonusTile(bonus, i) {
      if (bonus.kind === "playtime") {
        const hrs = bonus.value;
        const value = hrs < 1 ? Math.round(hrs * 60) + " min" : this.fmt(hrs, 1) + " hrs";
        return {
          key: "bonus-" + i, icon: "gamepad", bg: "bg-emerald-600/20", color: "text-emerald-400",
          label: "Average Playtime", value, caption: "Per Day",
        };
      }
      if (bonus.kind === "length") {
        return {
          key: "bonus-" + i, icon: "book-open", bg: "bg-emerald-600/20", color: "text-emerald-400",
          label: "Average Length", value: this.fmt(bonus.value, 0), caption: "Pages",
        };
      }
      return {
        key: "bonus-" + i, icon: bonus.icon, bg: "bg-emerald-600/20", color: "text-emerald-400",
        label: bonus.label, value: this.fmt(bonus.value, 2) + " " + bonus.unit, caption: "",
      };
    },

    averageRatingRows() {
      const types = this.selectedMediaType === "all"
        ? this.mediaTypeOptions.filter((opt) => opt.value !== "all")
        : this.mediaTypeOptions.filter((opt) => opt.value === this.selectedMediaType);
      const scaleMax = this.ratingScaleMax || 10;
      return types
        .map((opt) => {
          const visuals = MEDIA_TYPE_VISUALS[opt.value] || {};
          const score = this.summaryStatsByType[opt.value]
            ? this.summaryStatsByType[opt.value].average_score
            : null;
          const pct = score !== null && score !== undefined
            ? Math.max(0, Math.min(100, (score / scaleMax) * 100))
            : 0;
          return {
            value: opt.value,
            label: opt.label,
            average_score: score,
            average_score_display: score !== null && score !== undefined ? score.toFixed(1) : "",
            icon: visuals.icon || "",
            color: visuals.color || "#9ca3af",
            pct: pct,
          };
        })
        .filter((row) => row.average_score !== null && row.average_score !== undefined)
        .sort((a, b) => b.average_score - a.average_score);
    },

    get currentTypeLabel() {
      const labels = {
        all: "titles", movie: "films", tv: "shows", game: "games",
        book: "books", anime: "titles", music: "albums", podcast: "podcasts",
        comic: "comics", manga: "manga",
      };
      return labels[this.selectedMediaType] || "titles";
    },

    get currentTypeFlavor() {
      const flavors = {
        all: "stories, ideas, and worlds",
        movie: "film and storytelling",
        tv: "episodes and seasons",
        game: "play and adventure",
        book: "reading and discovery",
        anime: "anime and storytelling",
        music: "music and discovery",
        podcast: "listening and learning",
        comic: "comics and art",
        manga: "manga and art",
      };
      return flavors[this.selectedMediaType] || "stories, ideas, and worlds";
    },

    init() {
      const urlParams = new URLSearchParams(window.location.search);
      const startDateParam = urlParams.get("start-date");
      const endDateParam = urlParams.get("end-date");
      const compareParam = urlParams.get("compare");
      const mediaTypeParam = urlParams.get("media-type");

      if (startDateParam && endDateParam) {
        this.startDate = startDateParam;
        this.endDate = endDateParam;
      } else if (initialStartDate && initialEndDate) {
        this.startDate = initialStartDate;
        this.endDate = initialEndDate;
      } else if (initialRangeName) {
        this.updateDatesFromRange(initialRangeName);
      }

      this.detectRangeFromDates(initialRangeName);
      this.compareMode = this.normalizeCompareMode(compareParam || initialCompareMode);

      if (mediaTypeParam && this.mediaTypeOptions.some((o) => o.value === mediaTypeParam)) {
        this.selectedMediaType = mediaTypeParam;
      }

      const summaryEl = document.getElementById("summary_stats_by_type");
      if (summaryEl) {
        try { this.summaryStatsByType = JSON.parse(summaryEl.textContent); } catch (_) {}
      }

      const consumptionEl = document.getElementById("consumption_stats_by_type");
      if (consumptionEl) {
        try { this.consumptionStatsByType = JSON.parse(consumptionEl.textContent); } catch (_) {}
      }

      window.addEventListener("stats-charts-initialized", () => {
        if (this.selectedMediaType !== "all") {
          this.updateFilteredCharts();
        }
      });
    },

    toggleRangeDropdown() {
      this.isRangeOpen = !this.isRangeOpen;
      if (this.isRangeOpen) {
        this.isCompareOpen = false;
        this.isMediaTypeOpen = false;
      }
    },

    toggleCompareDropdown() {
      if (!this.hasFiniteRange()) {
        return;
      }

      this.isCompareOpen = !this.isCompareOpen;
      if (this.isCompareOpen) {
        this.isRangeOpen = false;
        this.isMediaTypeOpen = false;
      }
    },

    toggleMediaTypeDropdown() {
      this.isMediaTypeOpen = !this.isMediaTypeOpen;
      if (this.isMediaTypeOpen) {
        this.isRangeOpen = false;
        this.isCompareOpen = false;
      }
    },

    selectMediaType(value) {
      this.selectedMediaType = value;
      this.isMediaTypeOpen = false;
      const url = new URL(window.location.href);
      if (value === "all") {
        url.searchParams.delete("media-type");
      } else {
        url.searchParams.set("media-type", value);
      }
      window.history.replaceState({}, "", url.toString());
      this.$nextTick(() => {
        this.updateFilteredCharts();
        window.dispatchEvent(new CustomEvent("stats-media-type-changed"));
      });
    },

    updateFilteredCharts() {
      const type = this.selectedMediaType;
      if (typeof Chart === "undefined") return;
      const chart = Chart.getChart("scoreStackedChartCopy");
      if (chart) {
        const labelToType = {
          "TV Show": "tv", "TV Season": "tv",
          "Movie": "movie",
          "Anime": "anime",
          "Manga": "manga",
          "Game": "game",
          "Book": "book",
          "Comic": "comic", "Comic Issue": "comic",
          "Board Game": "boardgame",
          "Music": "music",
          "Podcast": "podcast",
        };
        chart.data.datasets.forEach((ds) => {
          const dsType = ds.media_type || labelToType[ds.label];
          ds.hidden = type !== "all" && dsType !== type;
        });
        chart.update("none");
      }
    },

    isMediaTypeVisible(type) {
      return this.selectedMediaType === "all" || this.selectedMediaType === type;
    },

    mediaTypeTriggerLabel() {
      if (this.selectedMediaType === "all") return "All media";
      const opt = this.mediaTypeOptions.find((o) => o.value === this.selectedMediaType);
      return opt ? opt.label : "All media";
    },

    hasFiniteRange() {
      return Boolean(
        this.startDate &&
          this.endDate &&
          this.startDate !== "all" &&
          this.endDate !== "all",
      );
    },

    normalizeCompareMode(mode) {
      if (!this.hasFiniteRange()) {
        return "none";
      }

      return this.comparisonOptions.some((option) => option.value === mode)
        ? mode
        : "previous_period";
    },

    getRangeDisplayName(rangeName = this.selectedRange) {
      const range = this.predefinedRanges.find((entry) => entry.name === rangeName);
      return range ? range.displayName : rangeName;
    },

    rangeTriggerLabel() {
      return this.isKnownPredefinedRange(this.selectedRange)
        ? this.getRangeDisplayName(this.selectedRange)
        : "Custom range";
    },

    currentRangeSummaryLabel() {
      if (!this.hasFiniteRange()) {
        return "All activity";
      }
      return this.formatDateRange(this.startDate, this.endDate);
    },

    comparisonTriggerLabel() {
      const option = this.comparisonOptions.find(
        (entry) => entry.value === this.compareMode,
      );
      return option ? option.label : "Previous period";
    },

    comparisonSummaryLabel(mode = this.compareMode) {
      if (mode === "none") {
        return "";
      }

      const range = this.getComparisonRange(mode);
      if (!range) {
        return "";
      }

      return this.formatDateRange(range.start, range.end);
    },

    isComparisonDisabled(mode) {
      return mode !== "none" && !this.hasFiniteRange();
    },

    async selectComparisonMode(mode) {
      if (this.isComparisonDisabled(mode) || this.compareMode === mode) {
        this.isCompareOpen = false;
        return;
      }

      const previousMode = this.compareMode;
      this.compareMode = mode;
      this.isCompareOpen = false;
      try {
        await this.saveCompareModePreference(mode);
      } catch (error) {
        this.compareMode = previousMode;
        console.error("Failed to save statistics compare mode:", error);
        return;
      }
      this.applyDateFilter();
    },

    selectPredefinedRange(rangeName) {
      this.selectedRange = rangeName;
      this.updateDatesFromRange(rangeName);
      this.isRangeOpen = false;
      this.applyDateFilter();
    },

    updateDatesFromRange(rangeName) {
      const range = this.calculateRangeDates(rangeName);
      if (!range) {
        return;
      }

      this.startDate = range.start;
      this.endDate = range.end;
      this.compareMode = this.normalizeCompareMode(this.compareMode);
    },

    calculateRangeDates(rangeName) {
      const rangeToday = new Date();
      rangeToday.setHours(0, 0, 0, 0);
      let start = new Date(rangeToday);
      let end = new Date(rangeToday);

      switch (rangeName) {
        case "Today":
          break;
        case "Yesterday":
          start.setDate(start.getDate() - 1);
          end = new Date(start);
          break;
        case "This Week": {
          const dayOfWeek = rangeToday.getDay();
          const diffToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
          start.setDate(start.getDate() - diffToMonday);
          break;
        }
        case "Last 7 Days":
          start.setDate(start.getDate() - 6);
          break;
        case "This Month":
          start = new Date(rangeToday.getFullYear(), rangeToday.getMonth(), 1);
          break;
        case "Last 30 Days":
          start.setDate(start.getDate() - 29);
          break;
        case "Last 90 Days":
          start.setDate(start.getDate() - 89);
          break;
        case "This Year":
          start = new Date(rangeToday.getFullYear(), 0, 1);
          break;
        case "Last 6 Months":
          start = new Date(rangeToday);
          start.setMonth(start.getMonth() - 6);
          if (start.getDate() !== rangeToday.getDate()) {
            start = new Date(start.getFullYear(), start.getMonth() + 1, 0);
          }
          break;
        case "Last 12 Months":
          start = new Date(rangeToday);
          start.setFullYear(start.getFullYear() - 1);
          if (start.getDate() !== rangeToday.getDate()) {
            start = new Date(start.getFullYear(), start.getMonth() + 1, 0);
          }
          break;
        case "All Time":
          return { start: "all", end: "all" };
        default:
          return null;
      }

      return {
        start: formatDateForInput(start),
        end: formatDateForInput(end),
      };
    },

    getPredefinedRangeDatesLabel(rangeName) {
      const range = this.calculateRangeDates(rangeName);
      if (!range) {
        return "";
      }
      if (range.start === "all" && range.end === "all") {
        return "All activity";
      }
      return this.formatDateRange(range.start, range.end);
    },

    updateDateRange() {
      if (this.hasFiniteRange() && parseLocalDate(this.endDate) < parseLocalDate(this.startDate)) {
        this.endDate = this.startDate;
      }

      this.customRangeLabel = this.formatDateRange(this.startDate, this.endDate);
      this.compareMode = this.normalizeCompareMode(this.compareMode);
    },

    applyCustomRange() {
      this.customRangeLabel = this.formatDateRange(this.startDate, this.endDate);
      this.selectedRange = this.customRangeLabel;
      this.isRangeOpen = false;
      this.applyDateFilter();
    },

    applyDateFilter() {
      const url = new URL(window.location.href);
      url.searchParams.set("start-date", this.startDate);
      url.searchParams.set("end-date", this.endDate);
      url.searchParams.set("compare", this.normalizeCompareMode(this.compareMode));
      if (this.selectedMediaType && this.selectedMediaType !== "all") {
        url.searchParams.set("media-type", this.selectedMediaType);
      } else {
        url.searchParams.delete("media-type");
      }
      window.location.href = url.toString();
    },

    async saveCompareModePreference(mode) {
      if (!compareModeUpdateUrl) {
        return;
      }

      const body = new URLSearchParams();
      body.set("compare_mode", mode);

      const response = await fetch(compareModeUpdateUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: body.toString(),
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || "Failed to save compare mode");
      }
    },

    formatDisplayDate(dateString) {
      if (!dateString || dateString === "all") {
        return "All time";
      }

      const date = parseLocalDate(dateString);
      const format = this.getDateFormat();

      if (!format) {
        return date.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
      }

      return this.formatDateByDjangoFormat(date, format);
    },

    getDateFormat() {
      const scriptTag = document.querySelector("script[data-date-format]");
      const selectedFormat = scriptTag?.dataset.dateFormat;
      const dateFormats = this.getDateFormatValues();

      if (
        selectedFormat &&
        (!dateFormats.length || dateFormats.includes(selectedFormat))
      ) {
        return selectedFormat;
      }

      return dateFormats[0] || "";
    },

    getDateFormatValues() {
      const formatsElement = document.getElementById("date_format_values");

      if (!formatsElement?.textContent) {
        return [];
      }

      try {
        const dateFormats = JSON.parse(formatsElement.textContent);
        return Array.isArray(dateFormats) ? dateFormats : [];
      } catch {
        return [];
      }
    },

    formatDateByDjangoFormat(date, djangoFormat) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      const shortMonth = date.toLocaleString(undefined, { month: "short" });
      const longMonth = date.toLocaleString(undefined, { month: "long" });
      const shortWeekday = date.toLocaleString(undefined, { weekday: "short" });
      const longWeekday = date.toLocaleString(undefined, { weekday: "long" });
      const ordinalSuffix = this.getOrdinalSuffix(date.getDate());

      const formatters = {
        d: () => day,
        D: () => shortWeekday,
        F: () => longMonth,
        j: () => String(date.getDate()),
        l: () => longWeekday,
        m: () => month,
        M: () => shortMonth,
        n: () => String(date.getMonth() + 1),
        S: () => ordinalSuffix,
        y: () => String(year).slice(-2),
        Y: () => String(year),
      };

      let formattedDate = "";
      let isEscaped = false;

      for (const character of djangoFormat) {
        if (isEscaped) {
          formattedDate += character;
          isEscaped = false;
        } else if (character === "\\") {
          isEscaped = true;
        } else {
          formattedDate += formatters[character]?.() ?? character;
        }
      }

      return formattedDate;
    },

    getOrdinalSuffix(day) {
      if (day >= 11 && day <= 13) {
        return "th";
      }
      switch (day % 10) {
        case 1:
          return "st";
        case 2:
          return "nd";
        case 3:
          return "rd";
        default:
          return "th";
      }
    },

    formatDateRange(start, end) {
      if (!start || !end) {
        return "";
      }

      if (start === "all" && end === "all") {
        return "All activity";
      }

      const startLabel = this.formatDisplayDate(start);
      const endLabel = this.formatDisplayDate(end);
      return start === end ? startLabel : `${startLabel} - ${endLabel}`;
    },

    getComparisonRange(mode = this.compareMode) {
      if (this.isComparisonDisabled(mode)) {
        return null;
      }

      const currentStart = parseLocalDate(this.startDate);
      const currentEnd = parseLocalDate(this.endDate);
      let compareStart = new Date(currentStart);
      let compareEnd = new Date(currentEnd);

      if (mode === "previous_period") {
        const durationDays = Math.round(
          (currentEnd.getTime() - currentStart.getTime()) / 86400000,
        ) + 1;
        compareEnd = new Date(currentStart);
        compareEnd.setDate(compareEnd.getDate() - 1);
        compareStart = new Date(compareEnd);
        compareStart.setDate(compareStart.getDate() - (durationDays - 1));
      } else if (mode === "last_year") {
        compareStart = new Date(currentStart);
        compareEnd = new Date(currentEnd);
        compareStart.setFullYear(compareStart.getFullYear() - 1);
        compareEnd.setFullYear(compareEnd.getFullYear() - 1);
      } else {
        return null;
      }

      return {
        start: formatDateForInput(compareStart),
        end: formatDateForInput(compareEnd),
      };
    },

    detectRangeFromDates(preservedRangeName = "") {
      if (this.isKnownPredefinedRange(preservedRangeName)) {
        this.selectedRange = preservedRangeName;
        return;
      }

      if (this.startDate === "all" && this.endDate === "all") {
        this.selectedRange = "All Time";
        return;
      }

      const matchingRange = this.predefinedRanges.find((range) => {
        const calculated = this.calculateRangeDates(range.name);
        return (
          calculated &&
          calculated.start === this.startDate &&
          calculated.end === this.endDate
        );
      });

      if (matchingRange) {
        this.selectedRange = matchingRange.name;
        return;
      }

      this.customRangeLabel = this.formatDateRange(this.startDate, this.endDate);
      this.selectedRange = this.customRangeLabel;
    },

    isKnownPredefinedRange(rangeName) {
      return this.predefinedRanges.some((range) => range.name === rangeName);
    },

    async refreshStatistics() {
      if (!refreshUrl) {
        console.error("Refresh URL not available");
        return;
      }

      const isPredefinedRange = this.isKnownPredefinedRange(this.selectedRange);

      if (!isPredefinedRange) {
        this.refreshing = true;
        setTimeout(() => {
          window.location.reload();
        }, 100);
        return;
      }

      this.refreshing = true;
      try {
        const formData = new FormData();
        formData.append("range_name", this.selectedRange);
        if (csrfToken) {
          formData.append("csrfmiddlewaretoken", csrfToken);
        }

        const response = await fetch(refreshUrl, {
          method: "POST",
          body: formData,
        });

        if (response.ok) {
          // Signal the stats Alpine component to start CacheUpdater and show the
          // banner. All page reloads go through CacheUpdater which guards on
          // data.exists before reloading, preventing blank-page races.
          window.dispatchEvent(new CustomEvent('stats-cache-rebuild-started'));

          // Poll only to know when to stop the button spinner.
          const maxAttempts = 180;
          let attempts = 0;

          const pollForCompletion = async () => {
            attempts += 1;
            try {
              const params = new URLSearchParams({
                cache_type: "statistics",
                range_name: this.selectedRange,
              });
              const statusResponse = await fetch(
                `/api/cache-status/?${params.toString()}`,
              );

              if (statusResponse.ok) {
                const statusData = await statusResponse.json();
                const stillRefreshing =
                  statusData.is_refreshing ||
                  statusData.refresh_scheduled ||
                  !statusData.exists;

                if (!stillRefreshing || attempts >= maxAttempts) {
                  this.refreshing = false;
                } else {
                  setTimeout(pollForCompletion, 1000);
                }
              } else if (attempts >= 5) {
                this.refreshing = false;
              } else {
                setTimeout(pollForCompletion, 1000);
              }
            } catch (error) {
              console.error("Error polling cache status:", error);
              if (attempts >= 5) {
                this.refreshing = false;
              } else {
                setTimeout(pollForCompletion, 1000);
              }
            }
          };

          setTimeout(pollForCompletion, 1000);
        } else {
          console.error("Failed to refresh statistics");
          this.refreshing = false;
        }
      } catch (error) {
        console.error("Error refreshing statistics:", error);
        this.refreshing = false;
      }
    },
  };
}

function parseLocalDate(dateString) {
  const [year, month, day] = dateString.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function formatDateForInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

if (typeof window !== "undefined") {
  // Keep the controller on window for Alpine expressions in the statistics page.
  // The separate asset is loaded outside the inline Alpine scope.
  window.dateRangePicker = dateRangePicker;
}
