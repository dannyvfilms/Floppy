import React, { useState } from 'react';
import { mountRoot } from '../settings/root';
import { CalendarLinks } from './CalendarLinks';

function readPalette() {
  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    surface: token('--color-surface', '#27272a'),
    surfaceStrong: token('--color-surface-strong', '#3f3f46'),
    surfaceDim: token('--color-surface-dim', '#1f1f23'),
    border: token('--color-border', '#3f3f46'),
    text: token('--color-text', '#fafafa'),
    textSecondary: token('--color-text-secondary', '#d4d4d8'),
    textMuted: token('--color-text-muted', '#a1a1aa'),
    accent: token('--color-accent', '#6366f1'),
    accentStrong: token('--color-accent-strong', '#4f46e5'),
    accentText: token('--color-accent-contrast', '#ffffff'),
    link: token('--color-link', '#818cf8'),
  };
}

function Adapter({ props }) {
  const [palette] = useState(readPalette);

  async function copyLink(url) {
    if (!navigator.clipboard?.writeText) {
      throw new Error('Clipboard is unavailable');
    }
    await navigator.clipboard.writeText(url);
  }

  function download(url) {
    if (url) {
      window.location.assign(url);
    }
  }

  return <CalendarLinks
    {...props}
    palette={palette}
    onCopyLink={copyLink}
    onDownload={download} />;
}

export function mountCalendarLinks(host, props) {
  return mountRoot(host, <Adapter props={props} />);
}
