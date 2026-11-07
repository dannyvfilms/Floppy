import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { MusicView } from '../pages/MusicView';

const canvas = document.createElement('canvas');
canvas.width = canvas.height = 1;
const ctx = canvas.getContext('2d');

function resolveColor(value, fallback) {
  if (!value) return fallback;
  if (/^(?:#|rgba?\()/i.test(value.trim())) return value.trim();
  if (!ctx) return fallback;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = fallback;
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgba(${r}, ${g}, ${b}, ${a / 255})`;
}

function readPalette() {
  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => resolveColor(css.getPropertyValue(name).trim(), fallback);
  return {
    card: token('--color-surface', '#27272a'),
    text: token('--color-text', '#fafafa'),
    textSecondary: token('--color-text-secondary', '#d4d4d8'),
    textMuted: token('--color-text-muted', '#a1a1aa'),
    border: token('--color-surface-border', '#3f3f46'),
    link: token('--color-link', '#818cf8'),
    star: '#facc15',
    placeholder: token('--color-surface-strong', '#3f3f46'),
    chipBackground: 'rgba(24, 24, 27, 0.92)',
    chipText: '#ffffff',
    statusColors: {
      Completed: '#10b981',
      'In progress': token('--color-accent', '#6366f1'),
      Paused: '#f59e0b',
      Planning: '#38bdf8',
      Dropped: token('--color-danger', '#ef4444'),
    },
    rating: { lit: '#facc15', unlit: '#52525b', muted: token('--color-text-muted', '#a1a1aa'), focusStyle: {} },
  };
}

function openAlbum(album) {
  if (album.href) window.location.assign(album.href);
}

function Grid({ props }) {
  const [palette, setPalette] = useState(readPalette);
  useEffect(() => {
    const update = () => setPalette(readPalette());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    scheme.addEventListener('change', update);
    return () => {
      observer.disconnect();
      scheme.removeEventListener('change', update);
    };
  }, []);
  return <MusicView part="albums" albums={props.albums} labels={props.labels}
    palette={palette} onOpenAlbum={openAlbum} />;
}

export function mountMusicAlbums(host, props) {
  return mountRoot(host, <Grid props={props} />);
}
