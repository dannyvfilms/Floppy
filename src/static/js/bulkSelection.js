// Bind once: this script is re-evaluated on boosted (hx:boost) navigation.
if (!window.__floppyBulkSelectionBound) {
  window.__floppyBulkSelectionBound = true;
  document.addEventListener("alpine:init", () => {
    Alpine.data("bulkSelection", (configId, refreshId) => ({
      selectMode: false,
      selectedItemIds: [],
      config: {},

      init() {
        const configElement = document.getElementById(configId);
        if (configElement) {
          try {
            this.config = JSON.parse(configElement.textContent || "{}");
          } catch (error) {
            console.error("Failed to load bulk-action configuration", error);
          }
        }
      },

      toggleSelectMode() {
        this.selectMode = !this.selectMode;
        if (!this.selectMode) {
          this.selectedItemIds = [];
        }
      },

      isItemSelected(id) {
        return this.selectedItemIds.includes(String(id));
      },

      toggleItemSelected(id) {
        const key = String(id);
        if (this.selectedItemIds.includes(key)) {
          this.selectedItemIds = this.selectedItemIds.filter((item) => item !== key);
        } else {
          this.selectedItemIds = [...this.selectedItemIds, key];
        }
      },

      clearSelection() {
        this.selectedItemIds = [];
      },

      refresh() {
        const refreshButton = document.getElementById(refreshId);
        if (refreshButton && window.htmx) {
          htmx.trigger(refreshButton, "click");
        }
      },
    }));
  });
}
