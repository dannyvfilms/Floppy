// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppyDateTimePickerBound) {
  window.__floppyDateTimePickerBound = true;
  document.addEventListener("alpine:init", () => {
  Alpine.data("dateTimePicker", (config) => {
    const calendar = window.floppyCalendarState({
      ...config,
      calendarMode: "date-picker",
    });
    return {
    ...calendar,
    fieldName: config.fieldName,
    trackTime: Boolean(config.trackTime),
    use12Hour: Boolean(config.use12Hour),
    defaultNow: Boolean(config.defaultNow),
    suggestionLabel: config.suggestionLabel || "",
    suggestionDate: config.suggestionDate || "",
    suggestionRuntimeMinutes: config.suggestionRuntimeMinutes || "",
    runtimeMinutes: config.runtimeMinutes || "",
    copyFrom: config.copyFrom || "",
    copyAvailable: false,

    value: config.initialValue || "",
    open: false,
    isMobile: false,
    popoverStyle: "",
    hour24: 0,
    minute: 0,
    second: 0,

    init() {
      calendar.init.call(this);
      // Read the live DOM value rather than trusting the server-rendered config:
      // mediaForm's status-change auto-fill runs (and may mutate this field)
      // before this component initializes, since it lives in a parent x-init.
      const initialValue = this.$refs.hiddenInput.value || this.value;
      if (initialValue) {
        this.value = this.normalizeInitialValue(initialValue);
        this.$refs.hiddenInput.value = this.value;
      }
      this.syncFromValue();
      if (this.defaultNow && !this.value) {
        this.applyNow();
      }
      this.mediaQuery = window.matchMedia("(max-width: 39.99rem)");
      this.isMobile = this.mediaQuery.matches;
      this.mediaQueryHandler = (event) => {
        this.isMobile = event.matches;
      };
      this.mediaQuery.addEventListener("change", this.mediaQueryHandler);

      this.repositionHandler = () => {
        if (this.open) {
          this.positionPopover();
        }
      };
      window.addEventListener("resize", this.repositionHandler);
      window.addEventListener("scroll", this.repositionHandler, true);
      window.visualViewport?.addEventListener("resize", this.repositionHandler);
      window.visualViewport?.addEventListener("scroll", this.repositionHandler);

      this.$refs.hiddenInput.addEventListener("input", () => {
        if (this.$refs.hiddenInput.value !== this.value) {
          this.value = this.normalizeInitialValue(this.$refs.hiddenInput.value);
          this.syncFromValue();
        }
      });
    },

    destroy() {
      this.mediaQuery?.removeEventListener("change", this.mediaQueryHandler);
      window.removeEventListener("resize", this.repositionHandler);
      window.removeEventListener("scroll", this.repositionHandler, true);
      window.visualViewport?.removeEventListener("resize", this.repositionHandler);
      window.visualViewport?.removeEventListener("scroll", this.repositionHandler);
    },

    positionPopover() {
      const trigger = this.$refs.trigger;
      const pickerToggle = this.$refs.pickerToggle;
      if (!trigger && !pickerToggle) {
        this.popoverStyle = "";
        return;
      }

      // Mobile sizing is handled entirely by CSS (max-h-[85dvh]): `dvh` is
      // the dynamic viewport height, which browsers (Safari included) keep
      // in sync with actual visible space as toolbar chrome shows/hides.
      // A JS-computed pixel height (from window.innerHeight/visualViewport)
      // can be stale at the moment the popover opens and end up wrong on
      // Safari, so mobile deliberately gets no inline override here.
      if (this.isMobile) {
        this.popoverStyle = "";
        return;
      }

      const viewport = window.visualViewport;
      const viewportWidth = viewport ? viewport.width : window.innerWidth;
      const viewportHeight = viewport ? viewport.height : window.innerHeight;
      const margin = 8;
      const minHeight = 200;

      const triggerRect = trigger?.getBoundingClientRect();
      const rect =
        triggerRect?.width && triggerRect.height
          ? triggerRect
          : pickerToggle.getBoundingClientRect();
      const panelWidth = 352;
      let left = rect.left;
      if (left + panelWidth > viewportWidth - margin) {
        left = Math.max(margin, viewportWidth - panelWidth - margin);
      }

      // Clamp the popover's height to whatever viewport space is actually
      // available below (or above, if that's roomier) the trigger, so it
      // always fits on screen and scrolls internally instead of spilling
      // past the bottom of the window where it can't be reached.
      const spaceBelow = viewportHeight - rect.bottom - margin * 2;
      const spaceAbove = rect.top - margin * 2;
      let top;
      let maxHeight;
      if (spaceBelow >= minHeight || spaceBelow >= spaceAbove) {
        top = rect.bottom + margin;
        maxHeight = Math.max(minHeight, Math.min(spaceBelow, viewportHeight - margin * 2));
      } else {
        maxHeight = Math.max(minHeight, Math.min(spaceAbove, viewportHeight - margin * 2));
        top = Math.max(margin, rect.top - margin - maxHeight);
      }

      this.popoverStyle = `position: fixed; top: ${top}px; left: ${left}px; max-height: ${maxHeight}px;`;
    },

    get hasValue() {
      return Boolean(this.value);
    },

    get displayText() {
      const parts = this.parts();
      if (!parts) {
        return "";
      }

      const dateLabel = new Date(
        parts.y,
        parts.m - 1,
        parts.d,
      ).toLocaleDateString(document.documentElement.lang || undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
      if (!this.trackTime) {
        return dateLabel;
      }

      return `${dateLabel}, ${this.formatTimeLabel(parts.h, parts.min, parts.s)}`;
    },

    pad(value) {
      return String(value).padStart(2, "0");
    },

    normalizeInitialValue(value) {
      const [datePart, timePart] = value.trim().split(/[T ]/, 2);
      if (!timePart || !this.trackTime) {
        return datePart;
      }

      const [hour, minute, second] = timePart.split(":");
      const normalizedTime = `${hour}:${minute}`;
      return second && Number(second) !== 0
        ? `${datePart}T${normalizedTime}:${second}`
        : `${datePart}T${normalizedTime}`;
    },

    formatTimeLabel(hour24, minute, second) {
      if (!this.use12Hour) {
        return `${this.pad(hour24)}:${this.pad(minute)}:${this.pad(second)}`;
      }

      let hour = hour24 % 12;
      if (hour === 0) {
        hour = 12;
      }
      return `${hour}:${this.pad(minute)}:${this.pad(second)} ${hour24 >= 12 ? "PM" : "AM"}`;
    },

    parts() {
      return this.partsFor(this.value);
    },

    formatValueFromParts(y, m, d, h, min, s) {
      const datePart = `${y}-${this.pad(m)}-${this.pad(d)}`;
      if (!this.trackTime) {
        return datePart;
      }
      const minuteValue = `${datePart}T${this.pad(h)}:${this.pad(min)}`;
      return s ? `${minuteValue}:${this.pad(s)}` : minuteValue;
    },

    syncFromValue() {
      const parts = this.parts();
      const now = new Date();
      if (parts) {
        this.viewYear = parts.y;
        this.viewMonth = parts.m - 1;
        this.focusYear = parts.y;
        this.focusMonth = parts.m - 1;
        this.focusDay = parts.d;
        this.hour24 = parts.h;
        this.minute = parts.min;
        this.second = parts.s;
      } else {
        this.viewYear = now.getFullYear();
        this.viewMonth = now.getMonth();
        this.focusYear = now.getFullYear();
        this.focusMonth = now.getMonth();
        this.focusDay = now.getDate();
        this.hour24 = now.getHours();
        this.minute = now.getMinutes();
        this.second = now.getSeconds();
      }
    },

    isSelectedDay(cell) {
      const parts = this.parts();
      return Boolean(
        parts &&
          cell &&
          parts.y === cell.year &&
          parts.m - 1 === cell.month &&
          parts.d === cell.day,
      );
    },

    isFocusedDay(cell) {
      return Boolean(
        cell &&
          cell.day === this.focusDay &&
          cell.month === this.focusMonth &&
          cell.year === this.focusYear,
      );
    },

    selectDay(cell) {
      if (!cell) {
        return;
      }
      if (!cell.inMonth) {
        this.viewYear = cell.year;
        this.viewMonth = cell.month;
      }
      const parts = this.parts();
      const h = parts ? parts.h : this.hour24;
      const min = parts ? parts.min : this.minute;
      const s = parts ? parts.s : this.second;
      this.commit(
        this.formatValueFromParts(cell.year, cell.month + 1, cell.day, h, min, s),
      );
    },

    calendarDayIsSelected(cell) {
      return this.isSelectedDay(cell);
    },

    calendarDayTabIndex(cell) {
      return this.isFocusedDay(cell) ? 0 : -1;
    },

    selectCalendarDay(cell) {
      this.selectDay(cell);
    },

    applyTimeChange() {
      const parts = this.parts();
      const y = parts ? parts.y : this.viewYear;
      const m = parts ? parts.m : this.viewMonth + 1;
      const d = parts ? parts.d : new Date().getDate();
      this.commit(
        this.formatValueFromParts(y, m, d, this.hour24, this.minute, this.second),
      );
    },

    hourOptions() {
      if (this.use12Hour) {
        return Array.from({ length: 12 }, (_, index) => index + 1);
      }
      return Array.from({ length: 24 }, (_, index) => index);
    },

    minuteOptions() {
      return Array.from({ length: 60 }, (_, index) => index);
    },

    displayHour() {
      if (!this.use12Hour) {
        return this.hour24;
      }
      const hour = this.hour24 % 12;
      return hour === 0 ? 12 : hour;
    },

    formatHourOption(hour) {
      return this.use12Hour ? String(hour) : this.pad(hour);
    },

    meridiem() {
      return this.hour24 >= 12 ? "PM" : "AM";
    },

    setHour(hour) {
      if (!this.use12Hour) {
        this.hour24 = hour;
      } else {
        const isPM = this.hour24 >= 12;
        let hour24 = hour % 12;
        if (isPM) {
          hour24 += 12;
        }
        this.hour24 = hour24;
      }
      this.applyTimeChange();
    },

    setMinute(minute) {
      this.minute = minute;
      this.applyTimeChange();
    },

    setSecond(second) {
      this.second = second;
      this.applyTimeChange();
    },

    toggleMeridiem() {
      this.hour24 = this.hour24 >= 12 ? this.hour24 - 12 : this.hour24 + 12;
      this.applyTimeChange();
    },

    applyNow() {
      this.commit(this.formatValueFromDate(new Date()));
    },

    formatValueFromDate(date) {
      return this.formatValueFromParts(
        date.getFullYear(),
        date.getMonth() + 1,
        date.getDate(),
        date.getHours(),
        date.getMinutes(),
        date.getSeconds(),
      );
    },

    resolvedRuntimeMinutes() {
      const runtimeMinutes = Number.parseInt(this.runtimeMinutes, 10);
      return Number.isFinite(runtimeMinutes) && runtimeMinutes > 0
        ? runtimeMinutes
        : null;
    },

    setStatusForPreset(status) {
      const form = this.$refs.hiddenInput.closest("form");
      const statusField = form?.querySelector('[name="status"]');
      if (!statusField || statusField.value === status) {
        return;
      }

      let mediaForm = null;
      if (window.Alpine) {
        try {
          mediaForm = Alpine.$data(form);
        } catch {
          // Ignore Alpine lookup failures and still update the status field.
        }
      }

      if (mediaForm && "suppressStatusDateAutofill" in mediaForm) {
        mediaForm.suppressStatusDateAutofill = true;
      }
      try {
        statusField.value = status;
        statusField.dispatchEvent(new Event("change", { bubbles: true }));
      } finally {
        if (mediaForm && "suppressStatusDateAutofill" in mediaForm) {
          mediaForm.suppressStatusDateAutofill = false;
        }
      }
    },

    commitPairedValue(newValue) {
      const pairedFieldName =
        this.fieldName === "start_date"
          ? "end_date"
          : this.fieldName === "end_date"
            ? "start_date"
            : "";
      if (!pairedFieldName) {
        return;
      }

      const form = this.$refs.hiddenInput.closest("form");
      const pairedInput = form?.querySelector(`[name="${pairedFieldName}"]`);
      if (!pairedInput || pairedInput === this.$refs.hiddenInput) {
        return;
      }

      if (window.Alpine) {
        try {
          const picker = Alpine.$data(pairedInput.closest("[x-data]"));
          if (picker?.commit) {
            picker.commit(newValue);
            return;
          }
        } catch {
          // Fall through to updating the paired hidden input directly.
        }
      }

      pairedInput.value = newValue;
      window.trackModalClearAutoFilledField?.(form, pairedFieldName);
      window.trackModalDispatchInputEvents?.(pairedInput);
    },

    applyQuickAction(action) {
      if (action === "start-now") {
        this.setStatusForPreset("In progress");
        const now = new Date();
        const nowValue = this.formatValueFromDate(now);
        const runtimeMinutes = this.resolvedRuntimeMinutes();
        const endValue = this.formatValueFromDate(
          new Date(now.getTime() + (runtimeMinutes || 0) * 60000),
        );
        if (this.fieldName === "start_date") {
          this.commit(nowValue);
          this.commitPairedValue(endValue);
        } else if (this.fieldName === "end_date") {
          this.commit(endValue);
          this.commitPairedValue(nowValue);
        } else {
          this.commit(nowValue);
        }
        return;
      }

      if (action === "just-finished") {
        this.setStatusForPreset("Completed");
        const now = new Date();
        const nowValue = this.formatValueFromDate(now);
        const runtimeMinutes = this.resolvedRuntimeMinutes();
        const startValue = this.formatValueFromDate(
          new Date(now.getTime() - (runtimeMinutes || 0) * 60000),
        );
        if (this.fieldName === "start_date") {
          this.commit(startValue);
          this.commitPairedValue(nowValue);
        } else if (this.fieldName === "end_date") {
          this.commit(nowValue);
          this.commitPairedValue(startValue);
        } else {
          this.commit(nowValue);
        }
        return;
      }

      if (action === "release-date") {
        if (!this.resolvedSuggestionDate()) {
          return;
        }
        this.setStatusForPreset("Completed");
        this.applySuggestion();
      }
    },

    resolvedSuggestionDate() {
      return this.suggestionDate || "";
    },

    resolvedSuggestionLabel() {
      return this.suggestionLabel || gettext("Suggested date");
    },

    applySuggestion() {
      const iso = this.resolvedSuggestionDate();
      if (!iso) {
        return;
      }

      const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
      if ([y, m, d].some(Number.isNaN)) {
        return;
      }

      const parts = this.parts();
      const h = parts ? parts.h : this.hour24;
      const min = parts ? parts.min : this.minute;
      const s = parts ? parts.s : this.second;
      this.commit(this.formatValueFromParts(y, m, d, h, min, s));
      this.backfillStartDateIfNeeded();
    },

    copySourceValue() {
      if (!this.copyFrom) {
        return "";
      }
      const form = this.$refs.hiddenInput?.closest("form");
      return form?.querySelector(`[name="${this.copyFrom}"]`)?.value || "";
    },

    copyFromOther() {
      const sourceParts = this.partsFor(this.copySourceValue());
      if (!sourceParts) {
        return;
      }
      // No backfill on this path. The runtime-based auto-fill recomputes
      // start_date from end_date, which would immediately overwrite a copy into
      // start_date with end minus the runtime. commit() already marks
      // start_date as manually set when that is the field being written, and
      // backfillStartDateIfNeeded honours that flag, so a copy into start_date
      // survives later edits to end_date too. A copy into end_date leaves the
      // flag alone: the user has not touched start_date, so the auto-fill must
      // stay armed for it.
      this.commit(
        this.formatValueFromParts(
          sourceParts.y,
          sourceParts.m,
          sourceParts.d,
          sourceParts.h,
          sourceParts.min,
          sourceParts.s,
        ),
      );
    },

    partsFor(value) {
      if (!value) {
        return null;
      }
      const [datePart, timePart] = value.trim().split(/[T ]/, 2);
      const [y, m, d] = datePart.split("-").map(Number);
      if ([y, m, d].some(Number.isNaN)) {
        return null;
      }
      let h = 0;
      let min = 0;
      let s = 0;
      if (timePart) {
        const segments = timePart.split(":").map(Number);
        h = segments[0] || 0;
        min = segments[1] || 0;
        s = segments[2] || 0;
      }
      return { y, m, d, h, min, s };
    },

    backfillStartDateIfNeeded() {
      const runtimeMinutes = Number.parseInt(
        this.suggestionRuntimeMinutes || this.runtimeMinutes,
        10,
      );
      if (
        this.fieldName !== "end_date" ||
        !Number.isFinite(runtimeMinutes) ||
        runtimeMinutes <= 0 ||
        !this.trackTime
      ) {
        return;
      }

      const form = this.$refs.hiddenInput.closest("form");
      const startInput = form?.querySelector('[name="start_date"]');
      if (!startInput || startInput === this.$refs.hiddenInput) {
        return;
      }
      if (form && window.Alpine) {
        try {
          if (Alpine.$data(form).manualStartDate) {
            return;
          }
        } catch {
          // Ignore Alpine lookup failures.
        }
      }

      const parts = this.parts();
      if (!parts) {
        return;
      }

      const endDateTime = new Date(
        parts.y,
        parts.m - 1,
        parts.d,
        parts.h,
        parts.min,
        parts.s,
      );
      const startDateTime = new Date(
        endDateTime.getTime() - runtimeMinutes * 60000,
      );
      startInput.value = this.formatValueFromParts(
        startDateTime.getFullYear(),
        startDateTime.getMonth() + 1,
        startDateTime.getDate(),
        startDateTime.getHours(),
        startDateTime.getMinutes(),
        startDateTime.getSeconds(),
      );
      window.trackModalClearAutoFilledField?.(form, "start_date");
      window.trackModalDispatchInputEvents?.(startInput);
    },

    commit(newValue) {
      if (this.value === newValue) {
        return;
      }
      this.value = newValue;
      this.$refs.hiddenInput.value = newValue;
      this.syncFromValue();

      const form = this.$refs.hiddenInput.closest("form");
      window.trackModalClearAutoFilledField?.(form, this.fieldName);
      if (this.fieldName === "start_date" && form && window.Alpine) {
        try {
          Alpine.$data(form).manualStartDate = true;
        } catch {
          // Ignore Alpine lookup failures.
        }
      }
      window.trackModalDispatchInputEvents?.(this.$refs.hiddenInput);
    },

    clear() {
      if (!this.value) {
        this.closePicker();
        return;
      }

      this.value = "";
      this.$refs.hiddenInput.value = "";
      this.syncFromValue();

      const form = this.$refs.hiddenInput.closest("form");
      window.trackModalClearAutoFilledField?.(form, this.fieldName);
      if (this.fieldName === "start_date" && form) {
        if (window.Alpine) {
          try {
            Alpine.$data(form).manualStartDate = false;
          } catch {
            // Ignore Alpine lookup failures.
          }
        }
        const sentinel = form.querySelector('[name="start_date_cleared"]');
        if (sentinel) {
          sentinel.value = "1";
        }
      }
      window.trackModalDispatchInputEvents?.(this.$refs.hiddenInput);
      this.closePicker();
    },

    // Escape steps back through the picker before it reaches the modal:
    // years -> months -> days -> close the picker -> (next press) close the
    // modal. Bound with .capture on window so this runs before the modal's own
    // window listener; stopPropagation then keeps the event from ever reaching
    // it, which is what stopped a single press from closing everything.
    onEscape(event) {
      if (!this.open) {
        return;
      }

      if (this.pickerView === "years") {
        this.showMonthsView();
      } else if (this.pickerView === "months") {
        this.showDaysView();
      } else {
        this.closePicker();
      }

      event.stopPropagation();
      event.preventDefault();
    },

    openPicker() {
      this.open = true;
      this.copyAvailable = Boolean(this.copySourceValue());
      this.pickerView = "days";
      this.positionPopover();
      this.$nextTick(() => {
        this.positionPopover();
        const panel = this.$refs.panel;
        const target =
          panel?.querySelector('[data-day-cell][tabindex="0"]') ||
          panel?.querySelector("[data-day-cell]");
        target?.focus();
      });
    },

    closePicker() {
      if (!this.open) {
        return;
      }
      this.open = false;
      (this.$refs.trigger?.offsetParent
        ? this.$refs.trigger
        : this.$refs.pickerToggle
      )?.focus();
    },

    togglePicker() {
      if (this.open) {
        this.closePicker();
      } else {
        this.openPicker();
      }
    },

    focusCalendarCell(cellKey) {
      this.$refs.panel
        ?.querySelector(`[data-day-cell="${cellKey}"]`)
        ?.focus();
    },

    closeCalendar() {
      this.closePicker();
    },

    trapFocus(event) {
      const panel = this.$refs.panel;
      if (!panel) {
        return;
      }

      const focusable = Array.from(
        panel.querySelectorAll(
          'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.offsetParent !== null);
      if (!focusable.length) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    };
  });
  });
}
