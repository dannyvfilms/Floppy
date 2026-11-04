import React, { useEffect, useState } from 'react';
import { DetailHeader, DetailSynopsis } from './DetailComposition';

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
    background: color('--color-page-bg', '#18181b'),
    surface: color('--color-surface', '#27272a'),
    surfaceStrong: color('--color-surface-strong', '#3f3f46'),
    border: color('--color-surface-border', '#3f3f46'),
    text: color('--color-text', '#fafafa'),
    textSecondary: color('--color-text-secondary', '#d4d4d8'),
    textMuted: color('--color-text-muted', '#a1a1aa'),
    accent: color('--color-accent', '#6366f1'),
    accentStrong: color('--color-accent-strong', '#4f46e5'),
    accentContrast: '#ffffff',
    link: color('--color-link', '#818cf8'),
    danger: color('--color-danger', '#ef4444'),
    placeholder: color('--color-surface-strong', '#3f3f46'),
  };
}

function scopeFor(host) {
  return host.closest('.detail-flat-top, .detail-carousel-grid') || host.parentElement;
}

function readClamped(host) {
  const scope = scopeFor(host);
  const legacy = scope?.querySelector('[data-detail-composition-legacy="synopsis"]');
  const paragraphs = legacy ? [...legacy.querySelectorAll('p')].filter(paragraph => paragraph.textContent.trim()) : [];
  return paragraphs.some(paragraph => paragraph.scrollHeight > paragraph.clientHeight + 2);
}

function Adapter({ host, props }) {
  const [palette, setPalette] = useState(readPalette);
  const [clamped, setClamped] = useState(() => readClamped(host));

  useEffect(() => {
    const part = props.part === 'header' ? 'header' : 'synopsis';
    const scope = scopeFor(host);
    const legacy = scope ? scope.querySelectorAll(`[data-detail-composition-legacy="${part}"]`) : [];
    const hidden = [...legacy].map(element => [element, element.style.display]);
    hidden.forEach(([element]) => { element.style.display = 'none'; });
    return () => hidden.forEach(([element, display]) => { element.style.display = display; });
  }, [host, props.part]);

  useEffect(() => {
    setClamped(readClamped(host));
  }, [host, props.synopsis?.text]);

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

  if (props.part === 'header') {
    return <DetailHeader model={props} labels={props.labels} palette={palette} showArtwork={false} />;
  }
  const textLength = (props.synopsis?.text || '').length;
  return <DetailSynopsis
    model={{ ...props, synopsis: { ...(props.synopsis || {}), clamped: clamped || textLength > 240 } }}
    labels={props.labels}
    palette={palette} />;
}

export function DetailCompositionTheme({ host, props }) {
  return <Adapter host={host} props={props} />;
}
