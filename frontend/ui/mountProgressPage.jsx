import React, { useMemo } from 'react';
import { mountRoot } from '../settings/root';
import { ProgressPageView } from '../pages/ProgressPageView';
import { useProgressPage } from '../pages/useProgressPage';
import { usePalette } from './ProgressDetailTheme.web';
import { rootStyle } from './rootStyle.web';
import { withBasePath } from './basePath.web';

// Same-origin session request to /api/v1, the transport the native screen
// supplies from its auth session.
function request(path, { query } = {}) {
  const search = query ? `?${new URLSearchParams(query)}` : '';
  return window.fetch(`${withBasePath(path)}${search}`, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(response => {
      if (!response.ok) throw new Error(`Request failed: ${response.status}`);
      return response.json();
    });
}

function open(href) {
  if (href) window.location.href = href;
}

function ProgressPageAdapter() {
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
  const page = useProgressPage({ request });
  return <ProgressPageView page={page} palette={palette}
    onOpenShow={row => open(row.url)} onOpenEpisode={episode => open(episode.href)} onOpenSeasonOrEpisode={open} testID="progress-page" />;
}

export function mountProgressPage(host) {
  return mountRoot(host, <ProgressPageAdapter />);
}
