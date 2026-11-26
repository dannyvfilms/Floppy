import React, { useMemo, useState } from 'react';
import { mountRoot } from '../settings/root';
import { AnimeSeasonsPageView } from '../pages/AnimeSeasonsPageView';
import { animeSeasonsParams, applyAnimeSeasonsIntent } from '../pages/useAnimeSeasonsPage';
import { PageSlot, collectPageSlots } from './PageSlot.web';
import { usePalette } from './ProgressDetailTheme.web';
import { rootStyle } from './rootStyle.web';

// The server renders the page model and the media cards. The shared view owns
// the heading, stepper, filters and states; the cards stay server media cards
// (Track popup, status chip, hover actions) adopted through a page slot. A
// filter change or season step loads the page for the new query.
function AnimeSeasonsPageAdapter({ host, props }) {
  const slots = useMemo(() => collectPageSlots(host), [host]);
  const [busy, setBusy] = useState(false);
  const base = usePalette();
  const palette = useMemo(() => {
    const css = rootStyle();
    const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    return {
      ...base,
      border: base.surfaceBorder,
      accent: token('--color-accent', '#6366f1'),
      accentStrong: token('--color-accent', '#4f46e5'),
      accentText: token('--color-accent-contrast', '#ffffff'),
      danger: token('--color-error-text', '#ef4444'),
    };
  }, [base]);

  function go(intent) {
    const next = applyAnimeSeasonsIntent(props.query, intent);
    if (next === props.query) return;
    setBusy(true);
    const search = new URLSearchParams(animeSeasonsParams(next)).toString();
    window.location.assign(`${window.location.pathname}${search ? `?${search}` : ''}`);
  }

  return <AnimeSeasonsPageView page={props} palette={palette} busy={busy}
    content={<PageSlot source={slots['anime-seasons-content']} />}
    onChange={go}
    onStep={target => go({ type: 'step', year: target.year, season: target.season })}
    onOpenSettings={href => window.location.assign(href)}
    onRetry={() => window.location.reload()}
    testID="anime-seasons-page" />;
}

export function mountAnimeSeasonsPage(host, props) {
  return mountRoot(host, <AnimeSeasonsPageAdapter host={host} props={props} />);
}
