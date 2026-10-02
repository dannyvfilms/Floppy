// Sidebar saved views: expand/collapse per media type and drag-to-reorder.
// Bind once: this script is re-evaluated on boosted (hx:boost) navigation.
if (!window.__floppySavedViewsBound) {
  window.__floppySavedViewsBound = true;

  const loadSortable = () => {
    if (typeof Sortable !== "undefined") {
      return Promise.resolve();
    }
    console.warn(
      "Saved view drag-and-drop is unavailable because SortableJS could not be loaded.",
    );
    return Promise.reject(new Error("SortableJS unavailable"));
  };

  const storageKey = (mediaType) => `floppy:saved-views-open:${mediaType}`;

  const readOpen = (mediaType) => {
    try {
      return localStorage.getItem(storageKey(mediaType));
    } catch {
      return null;
    }
  };

  document.addEventListener("alpine:init", () => {
    Alpine.data("savedViewGroup", (mediaType, reorderUrl, csrfToken) => ({
      open: false,
      reordering: false,
      sortable: null,

      init() {
        const stored = readOpen(mediaType);
        // Opening one of this type's views always shows the group.
        const onSavedView = Boolean(this.$root.querySelector("[aria-current='page']"));
        this.open = onSavedView || stored === "1";
      },

      toggle() {
        this.open = !this.open;
        try {
          localStorage.setItem(storageKey(mediaType), this.open ? "1" : "0");
        } catch {
          // Storage can be unavailable (private mode); the toggle still works.
        }
      },

      startReorder() {
        this.open = true;
        this.reordering = true;
        loadSortable()
          .then(() => {
            this.sortable = Sortable.create(this.$refs.list, {
              animation: 150,
              draggable: "[data-saved-view-id]",
              handle: ".saved-view-drag-handle",
            });
          })
          .catch(() => {
            this.reordering = false;
          });
      },

      finishReorder() {
        const body = new URLSearchParams();
        body.append("media_type", mediaType);
        this.$refs.list.querySelectorAll("[data-saved-view-id]").forEach((row) => {
          body.append("ids", row.dataset.savedViewId);
        });
        if (this.sortable) {
          this.sortable.destroy();
          this.sortable = null;
        }
        this.reordering = false;
        fetch(reorderUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body,
        });
      },
    }));
  });
}
