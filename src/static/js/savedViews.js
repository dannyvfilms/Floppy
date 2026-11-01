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
    Alpine.directive("sidebar-reveal", (el, { expression }, { effect, evaluateLater, cleanup }) => {
      const evaluate = evaluateLater(expression);
      let initialized = false;
      let visible = false;
      let animation;
      effect(() => evaluate((value) => {
        const show = Boolean(value);
        if (!initialized) {
          initialized = true;
          visible = show;
          el.style.display = show ? "" : "none";
          return;
        }
        if (show === visible) return;
        visible = show;
        const start = el.getBoundingClientRect().height;
        animation?.cancel();
        el.style.display = "";
        el.style.overflow = "hidden";
        const end = show ? el.scrollHeight : 0;
        animation = el.animate([{ height: `${start}px` }, { height: `${end}px` }], {
          duration: 200,
          easing: "ease-in-out",
        });
        animation.onfinish = () => {
          el.style.display = show ? "" : "none";
          el.style.overflow = "";
          animation = null;
        };
      }));
      cleanup(() => animation?.cancel());
    });

    Alpine.data("sidebarNavigation", (userId) => ({
      navOpen: false,
      pinned: [],
      pinnedLists: [],
      listsOpen: false,
      keys: ["calendar", "collection", "custom", "history", "lists", "statistics", "tags"],

      init() {
        this.loadPinnedLists();
        this.listsOpen = readOpen("lists") === "1" || this.pinnedLists.some((item) => item.url === window.location.pathname);
        try {
          const saved = JSON.parse(localStorage.getItem(`floppy:sidebar-pins:${userId}`) || "[]");
          this.pinned = Array.isArray(saved) ? saved.filter((key) => this.keys.includes(key)) : [];
        } catch {
          this.pinned = [];
        }
      },

      loadPinnedLists() {
        try {
          const saved = JSON.parse(localStorage.getItem(`floppy:sidebar-lists:${userId}`) || "[]");
          this.pinnedLists = Array.isArray(saved) ? saved : [];
        } catch {
          this.pinnedLists = [];
        }
      },

      onPinnedListsChanged() {
        const count = this.pinnedLists.length;
        this.loadPinnedLists();
        if (this.pinnedLists.length > count) {
          this.listsOpen = true;
          if (!this.isPinned("lists")) this.navOpen = true;
        }
      },

      toggleLists() {
        this.listsOpen = !this.listsOpen;
        try { localStorage.setItem(storageKey("lists"), this.listsOpen ? "1" : "0"); }
        catch { /* The toggle still works without storage. */ }
      },

      unpinList(id) {
        this.pinnedLists = this.pinnedLists.filter((item) => item.id !== id);
        try {
          localStorage.setItem(`floppy:sidebar-lists:${userId}`, JSON.stringify(this.pinnedLists));
        } catch { /* Keep the current page usable without storage. */ }
        window.dispatchEvent(new Event("sidebar-lists-changed"));
      },

      isPinned(key) {
        return this.pinned.includes(key);
      },

      hasUnpinned() {
        return this.keys.some((key) => !this.isPinned(key));
      },

      togglePin(key) {
        this.pinned = this.isPinned(key)
          ? this.pinned.filter((item) => item !== key)
          : [...this.pinned, key];
        try {
          localStorage.setItem(`floppy:sidebar-pins:${userId}`, JSON.stringify(this.pinned));
        } catch {
          // The preference still works for the current page when storage is unavailable.
        }
      },
    }));

    Alpine.data("sidebarListPin", (userId, id, name, url) => ({
      pinned: false,
      init() { this.refresh(); },
      read() {
        try {
          const value = JSON.parse(localStorage.getItem(`floppy:sidebar-lists:${userId}`) || "[]");
          return Array.isArray(value) ? value : [];
        } catch { return []; }
      },
      refresh() { this.pinned = this.read().some((item) => item.id === id); },
      toggle() {
        const items = this.read().filter((item) => item.id !== id);
        if (!this.pinned) items.push({ id, name, url });
        try { localStorage.setItem(`floppy:sidebar-lists:${userId}`, JSON.stringify(items)); }
        catch { return; }
        window.dispatchEvent(new Event("sidebar-lists-changed"));
      },
    }));

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
