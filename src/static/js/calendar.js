(function() {
  // The year grid is laid out four to a row, so this wants to stay a
  // multiple of four. yearRange() and the year-view chevrons both read it,
  // so a page and a step can never disagree.
  const YEAR_PAGE_SIZE = 20;

  function parseMonth(value) {
    const match = /^(\d{4})-(\d{2})$/.exec(value || "");
    if (!match) {
      const now = new Date();
      return { year: now.getFullYear(), month: now.getMonth() };
    }
    return { year: Number(match[1]), month: Number(match[2]) - 1 };
  }

  function readJsonSet(id) {
    if (!id) {
      return new Set();
    }
    const script = document.getElementById(id);
    if (!script) {
      return new Set();
    }
    try {
      const values = JSON.parse(script.textContent || "[]");
      return new Set(Array.isArray(values) ? values : []);
    } catch {
      return new Set();
    }
  }

  window.floppyCalendarState = function(config = {}) {
    const initialMonth = parseMonth(config.initialMonth);
    return {
      calendarMode: config.calendarMode || "date-picker",
      markerScriptId: config.markerScriptId || "",
      selectableMarkerScriptId: config.selectableMarkerScriptId || "",
      hasSelectableMarkerSet: Boolean(config.selectableMarkerScriptId),
      markerDays: new Set(),
      selectableMarkerDays: new Set(),
      weekStartsMonday: config.weekStart !== "sunday",
      pickerView: "days",
      viewYear: initialMonth.year,
      viewMonth: initialMonth.month,
      focusYear: initialMonth.year,
      focusMonth: initialMonth.month,
      focusDay: 1,
      yearInput: "",

      init() {
        this.markerDays = readJsonSet(this.markerScriptId);
        this.selectableMarkerDays = readJsonSet(this.selectableMarkerScriptId);
      },

      monthLabel() {
        return new Date(this.viewYear, this.viewMonth, 1).toLocaleDateString(
          document.documentElement.lang || undefined,
          { month: "long", year: "numeric" },
        );
      },

      weekdayLabels() {
        return Array.from({ length: 7 }, (_, index) =>
          new Date(2024, 0, (this.weekStartsMonday ? 1 : 7) + index)
            .toLocaleDateString(document.documentElement.lang || undefined, { weekday: "short" }),
        );
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

      dateKey(cell) {
        return `${cell.year}-${String(cell.month + 1).padStart(2, "0")}-${String(cell.day).padStart(2, "0")}`;
      },

      cellKey(cell) {
        return this.dateKey(cell);
      },

      // Keep the six-row layout stable while navigating between months.
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

      isToday(cell) {
        const now = new Date();
        return (
          cell.year === now.getFullYear() &&
          cell.month === now.getMonth() &&
          cell.day === now.getDate()
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

      showMonthsView() {
        this.pickerView = "months";
      },

      showYearsView() {
        this.yearInput = String(this.viewYear);
        this.pickerView = "years";
      },

      showDaysView() {
        this.pickerView = "days";
      },

      gotoMonth(monthIndex) {
        this.viewMonth = monthIndex;
        this.pickerView = "days";
      },

      gotoPrevYear() {
        this.viewYear -= 1;
        this.yearInput = String(this.viewYear);
      },

      gotoNextYear() {
        this.viewYear += 1;
        this.yearInput = String(this.viewYear);
      },

      // The year view shows a whole YEAR_PAGE_SIZE block, so its chevrons step
      // a block. Stepping a single year there appears to do nothing: the grid
      // only shifts on the years that straddle a boundary.
      gotoPrevYearPage() {
        this.viewYear -= YEAR_PAGE_SIZE;
        this.yearInput = String(this.viewYear);
      },

      gotoNextYearPage() {
        this.viewYear += YEAR_PAGE_SIZE;
        this.yearInput = String(this.viewYear);
      },

      onYearInput(event) {
        const digits = event.target.value.replace(/\D/g, "").slice(0, 4);
        this.yearInput = digits;
        if (digits.length === 4) {
          this.viewYear = Number(digits);
        }
      },

      applyYearInput() {
        const year = Number(this.yearInput);
        if (Number.isInteger(year) && year >= 1000 && year <= 9999) {
          this.viewYear = year;
        } else {
          this.yearInput = String(this.viewYear);
        }
        this.pickerView = "months";
      },

      monthShortLabel(monthIndex) {
        return new Date(this.viewYear, monthIndex, 1).toLocaleDateString(undefined, {
          month: "short",
        });
      },

      yearRange() {
        const start =
          Math.floor(this.viewYear / YEAR_PAGE_SIZE) * YEAR_PAGE_SIZE;
        return Array.from({ length: YEAR_PAGE_SIZE }, (_, i) => start + i);
      },

      calendarDayHasActivity(cell) {
        return this.markerDays.has(this.dateKey(cell));
      },

      calendarDayIsInteractive() {
        return true;
      },

      calendarDayIsSelected() {
        return false;
      },

      calendarDayTabIndex() {
        return 0;
      },

      calendarDayAriaLabel(cell) {
        return this.calendarMode === "activity" &&
          this.calendarDayHasActivity(cell) &&
          this.calendarDayIsInteractive(cell)
          ? interpolate(gettext("View activity for %(date)s"), { date: this.dateKey(cell) }, true)
          : this.dateKey(cell);
      },

      calendarDayClass(cell) {
        if (this.calendarDayIsSelected(cell)) {
          return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm cursor-pointer transition-colors bg-[var(--color-accent)] text-white";
        }

        if (this.calendarMode === "activity") {
          if (this.calendarDayHasActivity(cell)) {
            return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm text-[var(--color-text)] cursor-pointer transition-colors hover:bg-[var(--color-surface-muted)]";
          }
          return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm text-[var(--color-text-muted)] opacity-40";
        }

        if (this.isToday(cell)) {
          return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm cursor-pointer transition-colors text-[var(--color-accent)] font-semibold hover:bg-[var(--color-surface-muted)]";
        }
        if (cell.inMonth) {
          return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm cursor-pointer transition-colors text-[var(--color-text)] hover:bg-[var(--color-surface-muted)]";
        }
        return "date-picker-day-cell relative inline-flex items-center justify-center rounded-md text-sm cursor-pointer transition-colors text-[var(--color-text-muted)] opacity-50 hover:bg-[var(--color-surface-muted)]";
      },

      selectCalendarDay() {},

      closeCalendar() {},

      focusCalendarCell() {},

      calendarDayKeydown(event, cell) {
        if (!cell) {
          return;
        }

        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (this.calendarDayIsInteractive(cell)) {
            this.selectCalendarDay(cell);
          }
          return;
        }

        if (event.key === "Escape") {
          this.closeCalendar();
          return;
        }

        const target = new Date(cell.year, cell.month, cell.day);
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
        this.$nextTick(() => this.focusCalendarCell(focusedKey));
      },
    };
  };
})();
