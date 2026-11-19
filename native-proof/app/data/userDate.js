// One date formatter for the native pages, matching the web's
// users.templatetags.user_tags.user_date_format: the server time zone (the web
// renders in it, not in the device's) and the user's date_format preference.
// `system_default` is Django's English DATE_FORMAT "N j, Y" ("Oct. 10, 2026").

const AP_MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'];
const SHORT_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

let preferences = { timeZone: 'UTC', dateFormat: 'system_default' };

export function setDatePreferences(next = {}) {
  preferences = {
    timeZone: next.timeZone || preferences.timeZone,
    dateFormat: next.dateFormat || preferences.dateFormat,
  };
}

let loading = null;

/**
 * Read the server time zone and the user's date format once (a failure leaves
 * the defaults and the next call retries). `request` is the session's request.
 */
export function loadDatePreferences(request) {
  if (!loading) {
    loading = Promise.allSettled([request('/api/v1/info/'), request('/api/v1/user/preferences/')])
      .then(([info, prefs]) => {
        setDatePreferences({
          timeZone: info.status === 'fulfilled' ? info.value?.timezone : undefined,
          dateFormat: prefs.status === 'fulfilled' ? (prefs.value?.preferences?.date_format || prefs.value?.date_format) : undefined,
        });
        if (info.status === 'rejected' || prefs.status === 'rejected') loading = null;
      });
  }
  return loading;
}

export function getDatePreferences() {
  return preferences;
}

function parts(value, timeZone) {
  const text = String(value || '');
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(text);
  const date = new Date(dateOnly ? `${text}T12:00:00Z` : text);
  if (Number.isNaN(date.getTime())) return null;
  let zone = dateOnly ? 'UTC' : timeZone;
  let found;
  try {
    found = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: 'numeric', day: 'numeric' })
      .formatToParts(date);
  } catch (error) {
    zone = 'UTC';
    found = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: 'numeric', day: 'numeric' })
      .formatToParts(date);
  }
  const pick = type => Number(found.find(part => part.type === type)?.value);
  return { year: pick('year'), month: pick('month'), day: pick('day') };
}

const pad = number => String(number).padStart(2, '0');

/** Format an ISO date or datetime the way the web page prints it; '' when unparsable. */
export function formatUserDate(value, options = preferences) {
  const found = parts(value, options.timeZone || preferences.timeZone);
  if (!found) return '';
  const { year, month, day } = found;
  switch (options.dateFormat) {
    case 'iso_8601': return `${year}-${pad(month)}-${pad(day)}`;
    case 'month_d_yyyy': return `${SHORT_MONTHS[month - 1]} ${pad(day)}, ${year}`;
    case 'd_mon_yyyy': return `${pad(day)} ${SHORT_MONTHS[month - 1]} ${year}`;
    case 'm_d_yyyy': return `${month}/${day}/${year}`;
    case 'd_m_yyyy': return `${day}/${month}/${year}`;
    case 'dd_mm_yyyy': return `${pad(day)}.${pad(month)}.${year}`;
    case 'yyyy_mm_dd': return `${year}/${pad(month)}/${pad(day)}`;
    case 'long_eu': return `${day} ${SHORT_MONTHS[month - 1]}, ${year}`;
    default: return `${AP_MONTHS[month - 1]} ${day}, ${year}`;
  }
}

function clock(value, timeZone) {
  const date = new Date(String(value || ''));
  if (Number.isNaN(date.getTime())) return null;
  let found;
  try {
    found = new Intl.DateTimeFormat('en-US', { timeZone, hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(date);
  } catch (error) {
    found = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(date);
  }
  const pick = type => Number(found.find(part => part.type === type)?.value);
  return { hour: pick('hour') % 24, minute: pick('minute') };
}

/** Django's "P" time format in English: "2:52 a.m.", "6 p.m.", "noon", "midnight". */
export function formatUserTime(value, options = preferences) {
  const time = clock(value, options.timeZone || preferences.timeZone);
  if (!time) return '';
  if (time.minute === 0 && time.hour === 0) return 'midnight';
  if (time.minute === 0 && time.hour === 12) return 'noon';
  const hour = time.hour % 12 || 12;
  const minutes = time.minute ? `:${pad(time.minute)}` : '';
  return `${hour}${minutes} ${time.hour < 12 ? 'a.m.' : 'p.m.'}`;
}

/** The web's datetime_format: the date, a space, the time ("Nov. 5, 2026 2:52 a.m."). */
export function formatUserDateTime(value, options = preferences) {
  const day = formatUserDate(value, options);
  const time = formatUserTime(value, options);
  return day && time ? `${day} ${time}` : day;
}
