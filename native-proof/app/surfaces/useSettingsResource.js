import { useCallback, useEffect, useRef, useState } from 'react';
import { createSettingsTransport } from '../data/settingsTransport';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';

// Loads one settings resource through the transport and tracks
// loading / signedOut / error / ready so every page renders real states.
// `load(transport)` returns the raw payload; reload() retries.
export function useSettingsResource(load) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [result, setResult] = useState({ state: 'loading', data: null, message: '' });
  const loadRef = useRef(load);
  loadRef.current = load;
  const [tick, setTick] = useState(0);

  useEffect(() => subscribeAuthSession(next => setSession(next)), []);

  useEffect(() => {
    let active = true;
    const transport = createSettingsTransport({ auth: session });
    setResult(current => ({ ...current, state: 'loading' }));
    Promise.resolve()
      .then(() => loadRef.current(transport))
      .then(data => { if (active) setResult({ state: 'ready', data, message: '' }); })
      .catch(error => {
        if (!active) return;
        setResult({
          state: error?.code === 'signed_out' ? 'signedOut' : 'error',
          data: null,
          message: error?.message || '',
        });
      });
    return () => { active = false; };
  }, [session, tick]);

  const reload = useCallback(() => setTick(count => count + 1), []);
  const transport = createSettingsTransport({ auth: session });
  return { ...result, reload, transport };
}
