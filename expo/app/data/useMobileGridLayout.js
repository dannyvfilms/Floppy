import { useEffect, useState } from 'react';
import { getActiveAuthSession, subscribeAuthSession } from './authSession';
import { createSettingsTransport } from './settingsTransport';

// The person's Mobile Grid preference (Comfortable: two across, Compact: three across), read
// from the server like Now Playing does, so Home and Search size their cards from one place.
export function useMobileGridLayout() {
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [layout, setLayout] = useState('compact');
  useEffect(() => subscribeAuthSession(setSession), []);
  useEffect(() => {
    if (!session) {
      setLayout('compact');
      return undefined;
    }
    let active = true;
    createSettingsTransport({ auth: session }).loadPreferences()
      .then(payload => {
        if (active) setLayout(payload?.preferences?.mobile_grid_layout === 'comfortable' ? 'comfortable' : 'compact');
      })
      .catch(() => {});
    return () => { active = false; };
  }, [session]);
  return layout;
}
