import React, { useEffect, useRef, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { ProgressChanger } from '../../../frontend/ui/ProgressChanger';
import { getActiveAuthSession } from '../data/authSession';
import { useAccountDisplay } from '../data/accountDisplay';
import { adjustProgressRequest, progressFromResponse } from '../data/homeProgressCore';
import { progressPalette } from '../theme';

// Native adapter for the Home quick progress changer. The shared control owns
// the presentation; this owns the write (`/api/v1/media/.../progress/`), its
// busy and flash state, and the value the card shows afterwards.
export default function HomeProgress({ progress, identity }) {
  const { width } = useWindowDimensions();
  const phone = width <= 768;
  const prefs = useAccountDisplay();
  const [state, setState] = useState(progress);
  const [busy, setBusy] = useState(null);
  const [flash, setFlash] = useState(null);
  const timer = useRef(null);
  useEffect(() => setState(progress), [progress]);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function onAdjust(operation) {
    const session = getActiveAuthSession();
    if (!session || !identity || busy) return;
    setBusy(operation);
    try {
      const response = await session.request(...adjustProgressRequest(identity, operation));
      setState(current => progressFromResponse(current, response));
      setFlash(operation);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setFlash(null), 600);
    } catch {
      setFlash(null);
    } finally {
      setBusy(null);
    }
  }

  return <ProgressChanger
    value={state.value}
    max={state.max}
    unit={phone && prefs.compact ? '' : state.unit}
    showMax={state.showMax}
    canDecrease={state.canDecrease && !!identity}
    canIncrease={state.canIncrease && !!identity}
    busyOperation={busy}
    flashOperation={flash}
    decreaseLabel={state.decreaseLabel}
    increaseLabel={state.increaseLabel}
    onAdjust={onAdjust}
    palette={{ ...progressPalette, compact: width < 600, showButtons: !phone || prefs.quick, minWidth: 28 }} />;
}
