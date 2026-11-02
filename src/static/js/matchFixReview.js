// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppyMatchFixReviewBound) {
  window.__floppyMatchFixReviewBound = true;
  document.addEventListener("alpine:init", () => {
    Alpine.data("matchFixReview", (dataId, labels) => ({
      labels,
      rows: {},
      episodes: [],
      filter: "all",
      openPicker: null,
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
        return this.rows[id];
      },

      needsChoice(id) {
        return !this.row(id).selected;
      },

      get needsCount() {
        return Object.keys(this.rows).filter((id) => this.needsChoice(id)).length;
      },

      visible(id) {
        return this.filter === "all" || this.needsChoice(id);
      },

      statusKey(id) {
        const row = this.row(id);
        if (!row.selected) {
          return "needs";
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
        };
        return { label: this.labels[key], classes: tone[key] };
      },

      episodeLabel(episodeId) {
        const found = this.episodes.find((item) => item.id === episodeId);
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

      choose(id, episodeId) {
        const row = this.row(id);
        row.selected = episodeId;
        row.touched = true;
        this.openPicker = null;
      },
    }));
  });
}
