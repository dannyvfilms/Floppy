// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppyEpisodeOrderReviewBound) {
  window.__floppyEpisodeOrderReviewBound = true;
  document.addEventListener("alpine:init", () => {
    Alpine.data("episodeOrderReview", (dataId, labels) => ({
      labels,
      rows: {},
      episodes: [],
      filter: "all",
      openPicker: null,
      openOptions: null,
      query: "",

      init() {
        const script = document.getElementById(dataId);
        if (!script) {
          return;
        }
        const data = JSON.parse(script.textContent);
        Object.values(data.rows).forEach((row) => {
          row.touched = false;
        });
        this.rows = data.rows;
        this.episodes = data.episodes;
      },

      row(id) {
        return this.rows[String(id)];
      },

      isCombined(id) {
        return this.row(id).combine !== String(id);
      },

      needsChoice(id) {
        const row = this.row(id);
        return !row.archive && !this.isCombined(id) && row.selected.length === 0;
      },

      get needsCount() {
        return Object.keys(this.rows).filter((id) => this.needsChoice(id)).length;
      },

      get pendingCount() {
        return Object.keys(this.rows).filter(
          (id) => this.needsChoice(id) && this.row(id).pending,
        ).length;
      },

      visible(id) {
        return this.filter === "all" || this.needsChoice(id);
      },

      statusKey(id) {
        const row = this.row(id);
        if (row.archive) {
          return "archived";
        }
        if (this.isCombined(id)) {
          return "combined";
        }
        if (row.selected.length === 0) {
          return row.pending ? "suggested" : "needs";
        }
        return row.touched ? "chosen" : row.kind;
      },

      statusChip(id) {
        const key = this.statusKey(id);
        const tone = {
          matched: "bg-emerald-500/20 border-emerald-500/50 text-[var(--color-text)]",
          chosen: "bg-emerald-500/20 border-emerald-500/50 text-[var(--color-text)]",
          suggested: "bg-indigo-500/20 border-indigo-500/50 text-[var(--color-text)]",
          needs: "bg-amber-500/20 border-amber-500/50 text-[var(--color-text)]",
          archived: "bg-[var(--color-surface)] text-[var(--color-text-muted)] border-[var(--color-surface-border)]",
          combined: "bg-[var(--color-surface)] text-[var(--color-text-muted)] border-[var(--color-surface-border)]",
        };
        return { label: this.labels[key], classes: tone[key] };
      },

      episode(episodeId) {
        return this.episodes.find((item) => item.id === episodeId);
      },

      episodeLabel(episodeId) {
        const found = this.episode(episodeId);
        return found ? `${found.code} ${found.title}` : episodeId;
      },

      pickerResults() {
        const needle = this.query.trim().toLowerCase();
        if (!needle) {
          return this.episodes;
        }
        return this.episodes.filter((item) =>
          `${item.code} ${item.title} ${item.air_date}`.toLowerCase().includes(needle),
        );
      },

      togglePicker(id) {
        this.openPicker = this.openPicker === id ? null : id;
        this.query = "";
      },

      toggleEpisode(id, episodeId) {
        const row = this.row(id);
        row.touched = true;
        row.selected = row.selected.includes(episodeId)
          ? row.selected.filter((value) => value !== episodeId)
          : [...row.selected, episodeId];
      },

      removeEpisode(id, episodeId) {
        const row = this.row(id);
        row.touched = true;
        row.selected = row.selected.filter((value) => value !== episodeId);
      },

      acceptSuggestion(id) {
        const row = this.row(id);
        if (row.pending) {
          row.selected = [row.pending];
          row.touched = true;
        }
      },

      acceptAllSuggestions() {
        Object.keys(this.rows).forEach((id) => {
          if (this.needsChoice(id)) {
            this.acceptSuggestion(id);
          }
        });
      },

      hasFollowers(id) {
        const own = String(id);
        return Object.keys(this.rows).some(
          (other) => other !== own && this.row(other).combine === own,
        );
      },

      // Archiving and combining exclude each other: a viewing that others are
      // folded into, or that is folded into another, cannot be archived.
      canArchive(id) {
        return !this.isCombined(id) && !this.hasFollowers(id);
      },

      // A viewing can be folded into another only if that one stays separate
      // and is not archived, and nothing is folded into this one.
      combineTargets(id) {
        const own = String(id);
        if (this.hasFollowers(id)) {
          return [];
        }
        return Object.keys(this.rows).filter(
          (other) =>
            other !== own && !this.isCombined(other) && !this.row(other).archive,
        );
      },
    }));
  });
}
