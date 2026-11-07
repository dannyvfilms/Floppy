import React, { useCallback, useEffect, useState } from 'react';
import { SearchResults as SharedSearchResults } from './SearchResults.jsx';
import { RatingStarIcon } from './RatingStarIcon.web';
import { RatingStars } from './RatingStars';

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
    text: color('--color-text', '#fafafa'),
    textSecondary: color('--color-text-secondary', '#d4d4d8'),
    textMuted: color('--color-text-muted', '#a1a1aa'),
    surface: color('--color-surface', '#27272a'),
    surfaceStrong: color('--color-surface-strong', '#3f3f46'),
    surfaceMuted: color('--color-surface-muted', '#52525b'),
    border: color('--color-surface-border', '#3f3f46'),
    accent: color('--color-accent', '#6366f1'),
    accentText: '#ffffff',
    link: color('--color-link', '#818cf8'),
    danger: color('--color-danger', '#ef4444'),
  };
}

function usePalette() {
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
  return palette;
}

function navigate(href) {
  if (!href) return;
  window.location.assign(href);
}

export function SearchResults({ props }) {
  const palette = usePalette();

  const onSelectScope = useCallback(option => navigate(option?.href), []);
  const onSelectLayout = useCallback(option => navigate(option?.href), []);
  const onSearchOnline = useCallback(target => navigate(target?.href), []);
  const onPage = useCallback(page => navigate(page?.href), []);
  const onOpenResult = useCallback(href => navigate(href), []);
  const onOpenLink = useCallback(href => navigate(href), []);

  const onAction = useCallback(action => {
    if (!action) return;
    if (action.kind === 'modal') {
      window.dispatchEvent(new CustomEvent('floppy-open-modal', { detail: action }));
      return;
    }
    if (action.kind === 'link') {
      navigate(action.href);
      return;
    }
    if (action.kind === 'post') {
      window.htmx?.ajax('POST', action.url, {
        target: action.target,
        swap: action.swap,
        values: action.vals,
        headers: { 'X-CSRFToken': action.csrfToken || '' },
      });
    }
  }, []);

  const onRate = useCallback((item, score) => {
    const rating = item?.rating;
    if (!rating?.rateUrl) return;
    window.htmx?.ajax('POST', rating.rateUrl, {
      swap: 'none',
      headers: { 'X-CSRFToken': item.csrfToken || '' },
      values: { score: score ?? rating.value, toggle: true },
    });
  }, []);

  const renderRating = useCallback(({ value, label, scaleMax, palette: ratingPalette, onSelect }) => (
    <RatingStars
      scaleMax={scaleMax}
      value={value}
      label={label}
      onSelect={onSelect}
      palette={ratingPalette}
      renderStar={lit => RatingStarIcon(lit)}
    />
  ), []);

  return <SharedSearchResults
    {...props}
    palette={{ ...palette, ...(props.palette || {}) }}
    onSelectScope={onSelectScope}
    onSelectLayout={onSelectLayout}
    onSearchOnline={onSearchOnline}
    onPage={onPage}
    onOpenResult={onOpenResult}
    onOpenLink={onOpenLink}
    onAction={onAction}
    onRate={onRate}
    renderRating={renderRating}
  />;
}
