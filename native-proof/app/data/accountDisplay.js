import { useEffect, useState } from 'react';
import { getActiveAuthSession } from './authSession';
import { setDatePreferences } from './userDate';

// The account preferences that change how a page prints: the web reads them in
// the template (mobile grid layout, quick season buttons, date format) and the
// server time zone. Loaded once per signed-in session and shared by pages.
const FALLBACK = { quick: false, compact: true, loaded: false };
let cache = { session: null, value: FALLBACK, pending: null };

function load(session) {
  if (cache.session === session && cache.pending) return cache.pending;
  const pending = Promise.allSettled([
    session.request('/api/v1/info/'),
    session.request('/api/v1/user/preferences/'),
  ]).then(([info, prefs]) => {
    const source = prefs.status === 'fulfilled' ? (prefs.value?.preferences || prefs.value || {}) : {};
    setDatePreferences({
      timeZone: info.status === 'fulfilled' ? info.value?.timezone : undefined,
      dateFormat: source.date_format,
    });
    cache.value = {
      quick: ['season_update', 'both'].includes(source.quick_season_update_mobile),
      compact: source.mobile_grid_layout !== 'comfortable',
      loaded: true,
    };
    return cache.value;
  });
  cache = { session, value: FALLBACK, pending };
  return pending;
}

export function useAccountDisplay() {
  const [value, setValue] = useState(() => (cache.session === getActiveAuthSession() ? cache.value : FALLBACK));
  useEffect(() => {
    const session = getActiveAuthSession();
    if (!session || typeof session.request !== 'function') return undefined;
    let live = true;
    load(session).then(next => { if (live) setValue(next); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return value;
}
