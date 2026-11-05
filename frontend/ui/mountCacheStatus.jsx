import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { CacheStatusCard } from './CacheStatusCard';
import { getCacheStatus } from './serviceWorkerStatus';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  background: 'var(--color-surface)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  success: 'var(--color-status-clean)',
  danger: 'var(--color-error-text)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  radius: 8,
  focusStyle: {},
};

const buttonPalette = {
  primary: {
    background: 'var(--color-accent)',
    pressed: 'var(--color-accent-strong)',
    hovered: 'var(--color-accent-strong)',
    text: '#ffffff',
    border: 'transparent',
  },
  surface: {
    background: 'var(--color-surface-strong)',
    pressed: 'var(--color-surface-muted)',
    hovered: 'var(--color-surface-muted)',
    text: 'var(--color-text)',
    border: 'var(--color-surface-border)',
  },
  radius: 6,
  focusStyle: {},
};

function CacheStatusAdapter({ props }) {
  const [status, setStatus] = useState({ loading: true, supported: true });

  const refresh = async () => {
    setStatus(current => ({ ...current, loading: true }));
    const next = await getCacheStatus();
    setStatus({ ...next, loading: false });
  };

  useEffect(() => {
    let live = true;
    getCacheStatus().then(next => {
      if (live) setStatus({ ...next, loading: false });
    });
    return () => { live = false; };
  }, []);

  return <CacheStatusCard status={status} onRefresh={refresh} busy={status.loading}
    copy={props.labels} palette={palette} buttonPalette={buttonPalette} />;
}

export function mountCacheStatus(host, props) {
  return mountRoot(host, <CacheStatusAdapter props={props} />);
}
