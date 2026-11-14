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

  const registerSidebar = (Alpine) => {
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

    // Sidebar pins live on the account. This copy is shared by the sidebar and
    // every list's "Pin to sidebar" button; changes post to the server.
    const readPins = () => {
      if (window.floppySidebarPins) return window.floppySidebarPins;
      let data = {};
      try { data = JSON.parse(document.getElementById("sidebar-pins-data")?.textContent || "{}"); }
      catch { data = {}; }
      window.floppySidebarPins = {
        nav: Array.isArray(data?.nav) ? data.nav : [],
        lists: Array.isArray(data?.lists) ? data.lists : [],
      };
      return window.floppySidebarPins;
    };
    const csrfToken = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
    const savePins = (url, next) => {
      window.floppySidebarPins = { nav: next.nav, lists: next.lists };
      window.dispatchEvent(new Event("sidebar-pins-changed"));
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify(window.floppySidebarPins),
      }).catch(() => { /* The pins still apply to this page. */ });
    };
    // Pins saved by older versions in this browser move to the account once.
    const adoptLocalPins = (url, userId) => {
      const current = readPins();
      if (current.nav.length || current.lists.length) return;
      const read = (key) => {
        try {
          const value = JSON.parse(localStorage.getItem(`floppy:sidebar-${key}:${userId}`) || "[]");
          return Array.isArray(value) ? value : [];
        } catch { return []; }
      };
      const nav = read("pins");
      const lists = read("lists");
      if (!nav.length && !lists.length) return;
      savePins(url, { nav, lists }).then(() => {
        try {
          localStorage.removeItem(`floppy:sidebar-pins:${userId}`);
          localStorage.removeItem(`floppy:sidebar-lists:${userId}`);
        } catch { /* Nothing to clean up without storage. */ }
      });
    };

    Alpine.data("sidebarNavigation", (pinsUrl, userId) => ({
      navOpen: false,
      pinned: [],
      pinnedLists: [],
      listsOpen: false,
      keys: ["calendar", "collection", "custom", "history", "lists", "rapid_rating", "statistics", "tags"],

      init() {
        adoptLocalPins(pinsUrl, userId);
        this.loadPins();
        const listsOpen = readOpen("lists");
        this.listsOpen = listsOpen === null
          ? this.pinnedLists.length > 0
          : listsOpen === "1" || this.pinnedLists.some((item) => item.url === window.location.pathname);
        if (this.pinnedLists.length) this.navOpen = true;
      },

      loadPins() {
        const pins = readPins();
        this.pinnedLists = pins.lists;
        this.pinned = pins.nav.filter((key) => this.keys.includes(key));
      },

      onPinnedListsChanged() {
        const count = this.pinnedLists.length;
        this.loadPins();
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
        savePins(pinsUrl, { nav: readPins().nav, lists: readPins().lists.filter((item) => item.id !== id) });
      },

      isPinned(key) {
        return this.pinned.includes(key);
      },

      hasUnpinned() {
        return this.keys.some((key) => !this.isPinned(key));
      },

      togglePin(key) {
        const nav = readPins().nav;
        savePins(pinsUrl, {
          nav: nav.includes(key) ? nav.filter((item) => item !== key) : [...nav, key],
          lists: readPins().lists,
        });
      },
    }));

    Alpine.data("sidebarListPin", (pinsUrl, id, name, url) => ({
      pinned: false,
      init() { this.refresh(); },
      refresh() { this.pinned = readPins().lists.some((item) => item.id === id); },
      toggle() {
        const { nav, lists } = readPins();
        const others = lists.filter((item) => item.id !== id);
        savePins(pinsUrl, { nav, lists: this.pinned ? others : [...others, { id, name, url }] });
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
  };
  if (window.Alpine) {
    registerSidebar(window.Alpine);
  } else {
    document.addEventListener("alpine:init", () => registerSidebar(window.Alpine), { once: true });
  }
}
