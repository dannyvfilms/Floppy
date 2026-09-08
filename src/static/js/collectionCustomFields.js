// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppyCollectionCustomFieldsBound) {
  window.__floppyCollectionCustomFieldsBound = true;
  document.addEventListener("alpine:init", () => {
    Alpine.data("collectionCustomFields", (config) => ({
      groups: [],
      fieldTypeChoices: config.fieldTypeChoices || [],
      mediaTypeChoices: config.mediaTypeChoices || [],
      saveUrl: config.saveUrl,
      itemId: config.itemId,
      itemMediaType: config.itemMediaType,
      hostId: config.hostId,
      manageFields: !!config.manageOpen,
      saving: false,
      error: "",
      nextClientId: 1,
      savedSchema: [],
      savedSnapshot: "",
      sortableLoadPromise: null,
      openMenu: null,
      menuStyle: {},

      toggleMenu(key, event) {
        if (this.openMenu === key) {
          this.openMenu = null;
          return;
        }
        const trigger = event.currentTarget;
        this.openMenu = key;
        this.$nextTick(() => this.positionDropdown(trigger));
      },

      positionDropdown(trigger) {
        if (!trigger) return;
        const rect = trigger.getBoundingClientRect();
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
        const viewportPadding = 16;
        const preferredHeight = 240;
        const spaceBelow = Math.max(0, viewportHeight - rect.bottom - viewportPadding);
        const spaceAbove = Math.max(0, rect.top - viewportPadding);
        const openUp = spaceAbove > spaceBelow;
        this.menuStyle = {
          position: "fixed",
          left: `${rect.left}px`,
          width: `${Math.max(rect.width, 160)}px`,
          maxHeight: `${Math.min(preferredHeight, openUp ? spaceAbove : spaceBelow)}px`,
          ...(openUp
            ? { bottom: `${viewportHeight - rect.top}px` }
            : { top: `${rect.bottom}px` }),
        };
      },

      init() {
        this.savedSchema = config.schema || [];
        this.groups = this.hydrate(this.savedSchema);
        this.savedSnapshot = JSON.stringify(this.serialize());
        if (this.manageFields) {
          this.$nextTick(() => this.initSortables());
        }
        this.$watch("manageFields", (open) => {
          if (open) {
            this.$nextTick(() => this.initSortables());
          }
        });
      },

      newClientId() {
        return `cf-${this.nextClientId++}`;
      },

      hydrate(schema) {
        return (schema || []).map((group) => ({
          client_id: this.newClientId(),
          id: group.id,
          name: group.name,
          fields: (group.fields || []).map((field) => ({
            client_id: this.newClientId(),
            id: field.id,
            label: field.label,
            field_type: field.field_type,
            options: field.options || [],
            optionsText: (field.options || []).join("\n"),
            media_types: [...(field.media_types || [])],
          })),
        }));
      },

      get dirty() {
        return JSON.stringify(this.serialize()) !== this.savedSnapshot;
      },

      addGroup() {
        this.groups.push({
          client_id: this.newClientId(),
          id: null,
          name: "",
          fields: [],
        });
        this.$nextTick(() => this.initSortables());
      },

      removeGroup(clientId) {
        this.groups = this.groups.filter((group) => group.client_id !== clientId);
      },

      addField(group) {
        group.fields.push({
          client_id: this.newClientId(),
          id: null,
          label: "",
          field_type: "text",
          options: [],
          optionsText: "",
          media_types: this.itemMediaType ? [this.itemMediaType] : [],
        });
        this.$nextTick(() => this.initSortables());
      },

      removeField(group, clientId) {
        group.fields = group.fields.filter((field) => field.client_id !== clientId);
      },

      toggleMediaType(field, value) {
        field.media_types = field.media_types.includes(value)
          ? field.media_types.filter((v) => v !== value)
          : [...field.media_types, value];
      },

      fieldTypeLabel(field) {
        const choice = this.fieldTypeChoices.find((c) => c.value === field.field_type);
        return choice ? choice.label : field.field_type;
      },

      mediaTypesLabel(field) {
        if (!field.media_types.length) return gettext("Media types");
        if (field.media_types.length === 1) {
          const choice = this.mediaTypeChoices.find(
            (c) => c.value === field.media_types[0],
          );
          return choice ? choice.label : field.media_types[0];
        }
        return interpolate(gettext("%(count)s selected"), { count: field.media_types.length }, true);
      },

      validateLocally() {
        for (const group of this.groups) {
          if (!group.name.trim()) {
            return gettext("Every group needs a name.");
          }
          for (const field of group.fields) {
            if (!field.label.trim()) {
              return gettext("Every field needs a label.");
            }
            if (!field.media_types.length) {
              return interpolate(gettext("\"%(label)s\" needs at least one media type."), { label: field.label }, true);
            }
          }
        }
        return "";
      },

      knownFieldIds() {
        // Only fields this form was rendered with may be deleted by a save.
        // Anything created since (by an import, or another tab) is untouched.
        return this.savedSchema.flatMap((group) =>
          (group.fields || []).map((field) => field.id).filter((id) => id != null),
        );
      },

      serialize() {
        return {
          item_id: this.itemId,
          known_field_ids: this.knownFieldIds(),
          groups: this.groups.map((group) => ({
            id: group.id,
            name: (group.name || "").trim(),
            fields: group.fields.map((field) => ({
              id: field.id,
              label: (field.label || "").trim(),
              field_type: field.field_type,
              media_types: [...field.media_types],
              options:
                field.field_type === "select"
                  ? field.optionsText
                      .split("\n")
                      .map((option) => option.trim())
                      .filter(Boolean)
                  : [],
            })),
          })),
        };
      },

      resetFields() {
        this.groups = this.hydrate(this.savedSchema);
      },

      csrfToken() {
        const input = document.querySelector(
          `#${this.hostId} input[name=csrfmiddlewaretoken]`,
        );
        if (input) return input.value;
        return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
      },

      async saveFields() {
        if (this.saving) return;
        const localError = this.validateLocally();
        if (localError) {
          this.error = localError;
          return;
        }
        this.saving = true;
        this.error = "";

        let response;
        let payload;
        try {
          response = await fetch(this.saveUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": this.csrfToken(),
            },
            body: JSON.stringify(this.serialize()),
          });
          payload = await response.json();
        } catch (e) {
          this.error = gettext("Could not save custom fields.");
          this.saving = false;
          return;
        }

        if (!response.ok || !payload.success) {
          this.error = (payload && payload.error) || gettext("Could not save custom fields.");
          this.saving = false;
          return;
        }

        const host = document.getElementById(this.hostId);
        if (host && payload.html) {
          host.innerHTML = payload.html;
          return;
        }

        this.groups = this.hydrate(payload.groups);
        this.savedSchema = payload.groups;
        this.savedSnapshot = JSON.stringify(this.serialize());
        this.manageFields = false;
        this.saving = false;
      },

      ensureSortable() {
        if (typeof Sortable !== "undefined") {
          return Promise.resolve(true);
        }
        if (!this.sortableLoadPromise) {
          this.sortableLoadPromise = new Promise((resolve) => {
            const existingScript = document.querySelector(
              "script[data-collection-fields-sortable]",
            );
            if (existingScript) {
              if (existingScript.dataset.loaded === "true") {
                resolve(true);
                return;
              }
              existingScript.addEventListener("load", () => resolve(true), {
                once: true,
              });
              existingScript.addEventListener("error", () => resolve(false), {
                once: true,
              });
              return;
            }

            const script = document.createElement("script");
            script.src = "https://cdn.jsdelivr.net/npm/sortablejs@1.15.3/Sortable.min.js";
            script.dataset.collectionFieldsSortable = "true";
            script.addEventListener(
              "load",
              () => {
                script.dataset.loaded = "true";
                resolve(true);
              },
              { once: true },
            );
            script.addEventListener(
              "error",
              () => {
                console.warn(
                  "Collection field drag-and-drop is unavailable because SortableJS could not be loaded.",
                );
                resolve(false);
              },
              { once: true },
            );
            document.head.appendChild(script);
          });
        }
        return this.sortableLoadPromise;
      },

      async initSortables() {
        const loaded = await this.ensureSortable();
        if (!loaded) return;

        const host = document.getElementById(this.hostId);
        if (!host) return;

        const groupsList = host.querySelector("[data-cf-group-list]");
        if (groupsList && !groupsList.dataset.sortableInit) {
          groupsList.dataset.sortableInit = "true";
          Sortable.create(groupsList, {
            animation: 150,
            handle: ".cf-group-handle",
            onEnd: () => {
              const orderedIds = Array.from(
                groupsList.querySelectorAll("[data-cf-group-client-id]"),
              ).map((node) => node.dataset.cfGroupClientId);
              this.groups = orderedIds
                .map((clientId) =>
                  this.groups.find((group) => group.client_id === clientId),
                )
                .filter(Boolean);
            },
          });
        }

        host.querySelectorAll("[data-cf-field-list]").forEach((fieldsList) => {
          if (fieldsList.dataset.sortableInit) return;
          fieldsList.dataset.sortableInit = "true";
          const groupClientId = fieldsList.dataset.cfFieldList;
          Sortable.create(fieldsList, {
            animation: 150,
            handle: ".cf-field-handle",
            onEnd: () => {
              const group = this.groups.find((g) => g.client_id === groupClientId);
              if (!group) return;
              const orderedIds = Array.from(
                fieldsList.querySelectorAll("[data-cf-field-client-id]"),
              ).map((node) => node.dataset.cfFieldClientId);
              group.fields = orderedIds
                .map((clientId) =>
                  group.fields.find((field) => field.client_id === clientId),
                )
                .filter(Boolean);
            },
          });
        });
      },
    }));
  });
}
