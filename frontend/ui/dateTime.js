const YEAR_PAGE_SIZE = 20;

export function pad2(value) {
  return String(value).padStart(2, '0');
}

export function dateKey(cell) {
  return `${cell.year}-${pad2(cell.month + 1)}-${pad2(cell.day)}`;
}

function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

export function parseDateValue(value) {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(
    String(value).trim(),
  );
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  if ([year, month, day].some(Number.isNaN)) return null;
  return {
    year,
    month,
    day,
    hour: Number(match[4] || 0),
    minute: Number(match[5] || 0),
    second: Number(match[6] || 0),
  };
}

export function normalizeValue(value, trackTime) {
  const parts = parseDateValue(value);
  if (!parts) return '';
  return formatValue(parts, trackTime);
}

export function formatValue(parts, trackTime) {
  if (!parts) return '';
  const datePart = `${parts.year}-${pad2(parts.month + 1)}-${pad2(parts.day)}`;
  if (!trackTime) return datePart;
  const timePart = `${pad2(parts.hour)}:${pad2(parts.minute)}`;
  return parts.second ? `${datePart}T${timePart}:${pad2(parts.second)}` : `${datePart}T${timePart}`;
}

export function valueFromDate(date, trackTime) {
  return formatValue({
    year: date.getFullYear(),
    month: date.getMonth(),
    day: date.getDate(),
    hour: date.getHours(),
    minute: date.getMinutes(),
    second: date.getSeconds(),
  }, trackTime);
}

function formatDateLabel(parts, locale) {
  if (!parts) return '';
  const date = new Date(parts.year, parts.month, parts.day);
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }).format(date);
  } catch {
    return `${parts.year}-${pad2(parts.month + 1)}-${pad2(parts.day)}`;
  }
}

function formatTimeLabel(parts, use12Hour) {
  if (!parts) return '';
  if (!use12Hour) {
    return `${pad2(parts.hour)}:${pad2(parts.minute)}:${pad2(parts.second)}`;
  }
  let hour = parts.hour % 12;
  if (hour === 0) hour = 12;
  return `${hour}:${pad2(parts.minute)}:${pad2(parts.second)} ${parts.hour >= 12 ? 'PM' : 'AM'}`;
}

export function formatDisplayText(parts, trackTime, use12Hour, locale) {
  if (!parts) return '';
  const dateLabel = formatDateLabel(parts, locale);
  if (!trackTime) return dateLabel;
  return `${dateLabel}, ${formatTimeLabel(parts, use12Hour)}`;
}

export function monthLabel(year, month, locale) {
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      month: 'long',
      year: 'numeric',
    }).format(new Date(year, month, 1));
  } catch {
    return `${year}-${pad2(month + 1)}`;
  }
}

export function monthShortLabel(year, month, locale) {
  try {
    return new Intl.DateTimeFormat(locale || undefined, { month: 'short' }).format(
      new Date(year, month, 1),
    );
  } catch {
    return String(month + 1);
  }
}

export function weekdayLabels(weekStart, locale) {
  const monday = weekStart !== 'sunday';
  return Array.from({ length: 7 }, (_, index) => {
    const day = monday ? index + 1 : index;
    try {
      return new Intl.DateTimeFormat(locale || undefined, { weekday: 'short' }).format(
        new Date(2024, 0, 7 + day),
      );
    } catch {
      return String(index + 1);
    }
  });
}

function makeCell(year, month, day, inMonth) {
  return { year, month, day, inMonth };
}

export function monthWeeks(year, month, weekStart) {
  const monday = weekStart !== 'sunday';
  const first = new Date(year, month, 1);
  const startOffset = monday ? (first.getDay() + 6) % 7 : first.getDay();
  const total = daysInMonth(year, month);
  const previousTotal = daysInMonth(year, month - 1);
  const cells = [];
  for (let index = startOffset; index > 0; index -= 1) {
    const date = new Date(year, month, 1 - index);
    cells.push(makeCell(date.getFullYear(), date.getMonth(), date.getDate(), false));
  }
  for (let day = 1; day <= total; day += 1) cells.push(makeCell(year, month, day, true));
  let nextDay = 1;
  while (cells.length < 42) {
    const date = new Date(year, month + 1, nextDay);
    cells.push(makeCell(date.getFullYear(), date.getMonth(), date.getDate(), false));
    nextDay += 1;
  }
  const weeks = [];
  for (let index = 0; index < cells.length; index += 7) weeks.push(cells.slice(index, index + 7));
  return weeks;
}

export function yearPage(year) {
  const start = Math.floor(year / YEAR_PAGE_SIZE) * YEAR_PAGE_SIZE;
  return Array.from({ length: YEAR_PAGE_SIZE }, (_, index) => start + index);
}

export function isSameDay(parts, cell) {
  return Boolean(
    parts && cell && parts.year === cell.year && parts.month === cell.month && parts.day === cell.day,
  );
}

export function isToday(cell, now) {
  return Boolean(
    cell && now && cell.year === now.getFullYear() && cell.month === now.getMonth() && cell.day === now.getDate(),
  );
}

export function displayHour(hour24, use12Hour) {
  if (!use12Hour) return hour24;
  const hour = hour24 % 12;
  return hour === 0 ? 12 : hour;
}

export function meridiem(hour24) {
  return hour24 >= 12 ? 'PM' : 'AM';
}

export function hour24FromDisplay(hour, pm) {
  let value = hour % 12;
  if (pm) value += 12;
  return value;
}

export function stepHour(hour24, amount, use12Hour) {
  if (!use12Hour) return (hour24 + amount + 24) % 24;
  const pm = hour24 >= 12;
  const current = displayHour(hour24, true);
  let next = current + amount;
  let nextPm = pm;
  if (next > 12) {
    next = 1;
    nextPm = !pm;
  } else if (next < 1) {
    next = 12;
    nextPm = !pm;
  }
  return hour24FromDisplay(next, nextPm);
}

export function stepMinute(minute, amount) {
  return (minute + amount + 60) % 60;
}

export function stepSecond(second, amount) {
  return (second + amount + 60) % 60;
}

export function nowParts(now) {
  return {
    year: now.getFullYear(),
    month: now.getMonth(),
    day: now.getDate(),
    hour: now.getHours(),
    minute: now.getMinutes(),
    second: now.getSeconds(),
  };
}

export function isMarkedDay(markerDays, cell) {
  return Boolean(markerDays && markerDays.includes(dateKey(cell)));
}

export function isSelectableDay(selectableDays, cell) {
  if (!selectableDays) return true;
  return selectableDays.includes(dateKey(cell));
}
