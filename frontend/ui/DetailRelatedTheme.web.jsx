import React, { useEffect, useState } from 'react';
import { DetailRelated } from './DetailRelated';
import { Icon } from './Icon';
import { openModal } from './ModalHost';

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
  const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const color = (name, fallback) => resolveColor(token(name, fallback), fallback);
  return {
    card: color('--color-surface', '#27272a'),
    text: color('--color-text', '#fafafa'),
    textSecondary: color('--color-text-secondary', '#d4d4d8'),
    textMuted: color('--color-text-muted', '#a1a1aa'),
    border: color('--color-surface-border', '#3f3f46'),
    link: color('--color-link', '#818cf8'),
    star: color('--color-warning', '#facc15'),
    chipBackground: 'rgba(24, 24, 27, 0.92)',
    chipText: '#ffffff',
    placeholder: color('--color-surface-strong', '#3f3f46'),
    progressTrack: 'rgba(24, 24, 27, 0.6)',
    progressFill: color('--color-accent', '#6366f1'),
    progressPaused: 'rgba(99, 102, 241, 0.4)',
    rating: {
      lit: color('--color-warning', '#facc15'),
      unlit: color('--color-surface-muted', '#52525b'),
      muted: color('--color-text-muted', '#a1a1aa'),
      focusStyle: {},
    },
  };
}

function runAction(model, action) {
  if (!action) return;
  if (action.kind === 'link') {
    if (action.href) window.location.assign(action.href);
    return;
  }
  if (action.kind === 'post') {
    window.htmx?.ajax('POST', action.url, {
      target: action.target,
      swap: action.swap,
      values: action.vals,
      headers: { 'X-CSRFToken': model?.csrfToken || model?.actions?.csrfToken || '' },
    });
    return;
  }
  openModal(action);
}

function rate(model, score) {
  const url = model?.rating?.rateUrl;
  if (!url) return;
  window.htmx?.ajax('POST', url, {
    swap: 'none',
    headers: { 'X-CSRFToken': model.csrfToken || '' },
    values: { score: score ?? model.rating.value, toggle: true },
  });
}

function Adapter({ props }) {
  const [palette, setPalette] = useState(readPalette);

  useEffect(() => {
    const update = () => setPalette(readPalette());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    scheme.addEventListener('change', update);
    return () => {
      observer.disconnect();
      scheme.removeEventListener('change', update);
    };
  }, []);

  return <DetailRelated
    model={props.model}
    labels={props.labels}
    palette={palette}
    onOpen={model => { if (model?.href) window.location.assign(model.href); }}
    onOpenLink={href => { if (href) window.location.assign(href); }}
    onOpenExternal={url => { if (url) window.open(url, '_blank', 'noopener,noreferrer'); }}
    onAction={runAction}
    onRate={rate}
    renderActionIcon={action => <Icon spec={action.icon} />} />;
}

export function DetailRelatedTheme({ host, props }) {
  return <Adapter host={host} props={props} />;
}
