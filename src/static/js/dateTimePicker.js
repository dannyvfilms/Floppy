document.addEventListener("alpine:init", () => {
  Alpine.data("dateTimePicker", (config) => ({
    fieldName: config.fieldName,
    trackTime: Boolean(config.trackTime),
    use12Hour: Boolean(config.use12Hour),
    weekStartsMonday: config.weekStart !== "sunday",
    suggestionLabel: config.suggestionLabel || "",
    suggestionDate: config.suggestionDate || "",
    suggestionRuntimeMinutes: config.suggestionRuntimeMinutes || "",

    value: config.initialValue || "",
    open: false,
    isMobile: false,
    popoverStyle: "",
    viewYear: 0,
    viewMonth: 0,
    focusYear: 0,
    focusMonth: 0,
    focusDay: 1,
    hour24: 0,
    minute: 0,
    second: 0,

    init() {
      // Read the live DOM value rather than trusting the server-rendered config:
      // mediaForm's status-change auto-fill runs (and may mutate this field)
      // before this component initializes, since it lives in a parent x-init.
      const initialValue = this.$refs.hiddenInput.value || this.value;
      if (initialValue) {
        this.value = this.normalizeInitialValue(initialValue);
        this.$refs.hiddenInput.value = this.value;
      }
      this.syncFromValue();
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
      if (!this.$refs.trigger) {
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

      const rect = this.$refs.trigger.getBoundingClientRect();
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
      ).toLocaleDateString(undefined, {
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
      if (!this.value) {
        return null;
      }

      // Django renders bound DateTimeField values with a space separator,
      // while values selected in this picker use the HTML datetime-local
      // format with a `T` separator.
      const [datePart, timePart] = this.value.trim().split(/[T ]/, 2);
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

    monthLabel() {
      return new Date(this.viewYear, this.viewMonth, 1).toLocaleDateString(
        undefined,
        { month: "long", year: "numeric" },
      );
    },

    weekdayLabels() {
      return this.weekStartsMonday
        ? ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        : ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
    },

    makeCell(day, inMonth, monthOffset) {
      let year = this.viewYear;
      let month = this.viewMonth + monthOffset;
      if (month < 0) {
        month = 11;
        year -= 1;
      } else if (month > 11) {
        month = 0;
        year += 1;
      }
      return { day, inMonth, month, year };
    },

    cellKey(cell) {
      return `${cell.year}-${cell.month}-${cell.day}`;
    },

    // Always renders a fixed 6-row (42-cell) grid, filled with faded/clickable
    // leading and trailing days from the adjacent months, so the popover's
    // height never changes when navigating between months.
    calendarWeeks() {
      const first = new Date(this.viewYear, this.viewMonth, 1);
      const startOffset = this.weekStartsMonday
        ? (first.getDay() + 6) % 7
        : first.getDay();
      const daysInMonth = new Date(
        this.viewYear,
        this.viewMonth + 1,
        0,
      ).getDate();
      const daysInPrevMonth = new Date(this.viewYear, this.viewMonth, 0).getDate();

      const cells = [];
      for (let i = startOffset; i > 0; i -= 1) {
        cells.push(this.makeCell(daysInPrevMonth - i + 1, false, -1));
      }
      for (let day = 1; day <= daysInMonth; day += 1) {
        cells.push(this.makeCell(day, true, 0));
      }
      let nextDay = 1;
      while (cells.length < 42) {
        cells.push(this.makeCell(nextDay, false, 1));
        nextDay += 1;
      }

      const weeks = [];
      for (let i = 0; i < cells.length; i += 7) {
        weeks.push(cells.slice(i, i + 7));
      }
      return weeks;
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

    isToday(cell) {
      if (!cell) {
        return false;
      }
      const now = new Date();
      return (
        cell.year === now.getFullYear() &&
        cell.month === now.getMonth() &&
        cell.day === now.getDate()
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

    gotoPrevMonth() {
      this.viewMonth -= 1;
      if (this.viewMonth < 0) {
        this.viewMonth = 11;
        this.viewYear -= 1;
      }
    },

    gotoNextMonth() {
      this.viewMonth += 1;
      if (this.viewMonth > 11) {
        this.viewMonth = 0;
        this.viewYear += 1;
      }
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
      const now = new Date();
      this.commit(
        this.formatValueFromParts(
          now.getFullYear(),
          now.getMonth() + 1,
          now.getDate(),
          now.getHours(),
          now.getMinutes(),
          now.getSeconds(),
        ),
      );
    },

    resolvedSuggestionDate() {
      return this.suggestionDate || "";
    },

    resolvedSuggestionLabel() {
      return this.suggestionLabel || "Suggested date";
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

    backfillStartDateIfNeeded() {
      const runtimeMinutes = Number.parseInt(this.suggestionRuntimeMinutes, 10);
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

    openPicker() {
      this.open = true;
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
      this.$refs.trigger?.focus();
    },

    togglePicker() {
      if (this.open) {
        this.closePicker();
      } else {
        this.openPicker();
      }
    },

    focusCell(cellKey) {
      this.$refs.panel
        ?.querySelector(`[data-day-cell="${cellKey}"]`)
        ?.focus();
    },

    onDayKeydown(event, cell) {
      if (!cell) {
        return;
      }

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.selectDay(cell);
        return;
      }

      if (event.key === "Escape") {
        this.closePicker();
        return;
      }

      const target = new Date(this.focusYear, this.focusMonth, this.focusDay);
      const weekdayOffset = this.weekStartsMonday
        ? (target.getDay() + 6) % 7
        : target.getDay();

      switch (event.key) {
        case "ArrowLeft":
          target.setDate(target.getDate() - 1);
          break;
        case "ArrowRight":
          target.setDate(target.getDate() + 1);
          break;
        case "ArrowUp":
          target.setDate(target.getDate() - 7);
          break;
        case "ArrowDown":
          target.setDate(target.getDate() + 7);
          break;
        case "Home":
          target.setDate(target.getDate() - weekdayOffset);
          break;
        case "End":
          target.setDate(target.getDate() + (6 - weekdayOffset));
          break;
        case "PageUp":
          target.setMonth(target.getMonth() - 1);
          break;
        case "PageDown":
          target.setMonth(target.getMonth() + 1);
          break;
        default:
          return;
      }

      event.preventDefault();
      this.focusYear = target.getFullYear();
      this.focusMonth = target.getMonth();
      this.focusDay = target.getDate();
      this.viewYear = this.focusYear;
      this.viewMonth = this.focusMonth;
      const focusedKey = this.cellKey({
        year: this.focusYear,
        month: this.focusMonth,
        day: this.focusDay,
      });
      this.$nextTick(() => this.focusCell(focusedKey));
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
  }));
});
