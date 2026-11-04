import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { HistoryFeed } from './HistoryFeed';

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
    surfaceMuted: color('--color-surface-muted', '#52525b'),
    border: color('--color-surface-border', '#3f3f46'),
    text: color('--color-text', '#fafafa'),
    textSecondary: color('--color-text-secondary', '#d4d4d8'),
    textMuted: color('--color-text-muted', '#a1a1aa'),
    accent: color('--color-accent', '#6366f1'),
    accentStrong: color('--color-accent-strong', '#4f46e5'),
    accentContrast: '#ffffff',
    link: color('--color-link', '#818cf8'),
    danger: color('--color-danger', '#ef4444'),
    mediaCard: {
      card: color('--color-surface', '#27272a'),
      text: color('--color-text', '#fafafa'),
      textSecondary: color('--color-text-secondary', '#d4d4d8'),
      textMuted: color('--color-text-muted', '#a1a1aa'),
      border: color('--color-surface-border', '#3f3f46'),
      link: color('--color-link', '#818cf8'),
      star: '#facc15',
      chipBackground: 'rgba(24, 24, 27, 0.92)',
      chipText: '#ffffff',
      placeholder: color('--color-surface-strong', '#3f3f46'),
      progressTrack: 'rgba(24, 24, 27, 0.6)',
      progressFill: color('--color-accent', '#6366f1'),
      progressPaused: 'rgba(99, 102, 241, 0.4)',
    },
  };
}

function assign(url) {
  if (url) window.location.assign(url);
}

function htmxGet(url, target, values) {
  if (!url) return;
  if (window.htmx?.ajax) {
    window.htmx.ajax('GET', url, { target, values, swap: 'innerHTML' });
    return;
  }
  assign(url);
}

function historyUrl(state, props) {
  const params = new URLSearchParams();
  if (state.from) params.set('start-date', state.from);
  if (state.to) params.set('end-date', state.to);
  if (state.mediaTypes?.length) params.set('media_type', state.mediaTypes.join(','));
  if (state.genre) params.set('genre', state.genre);
  if (state.impliedGenre) params.set('implied_genre', state.impliedGenre);
  if (state.mode && state.mode !== 'activity') params.set('history_mode', state.mode);
  const query = params.toString();
  return `${props.baseUrl || window.location.pathname}${query ? `?${query}` : ''}`;
}

function Adapter({ host, props }) {
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

  function navigate(intent) {
    if (intent?.url) assign(intent.url);
  }

  function loadMore(day) {
    htmxGet(day.nextUrl, day.nextTarget || host.closest('.history-day'));
  }

  function loadDay(day) {
    htmxGet(day.loadUrl, day.loadTarget || host.closest('.history-day'));
  }

  function openEntry(entry) {
    assign(entry.href);
  }

  function editEntry(entry) {
    if (entry.editUrl && entry.editTarget) {
      htmxGet(entry.editUrl, entry.editTarget, entry.editVals || {});
      return;
    }
    assign(entry.editUrl || entry.href);
  }

  function deleteEntry(entry) {
    if (!entry.deleteUrl) return;
    window.fetch(entry.deleteUrl, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': props.model?.csrfToken || '' },
    }).then(response => {
      if (!response.ok) throw new Error(`History delete failed: ${response.status}`);
      window.dispatchEvent(new CustomEvent('history-refresh-start'));
    }).catch(() => assign(entry.href || window.location.pathname));
  }

  function applyFilters(state) {
    assign(historyUrl(state, props));
  }

  function clearFilters() {
    assign(props.baseUrl || window.location.pathname);
  }

  function saveView(state) {
    const name = window.prompt(props.saveViewPrompt || 'Name this view');
    if (!name || !name.trim()) return;
    const body = new URLSearchParams();
    body.set('media_type', 'history');
    body.set('name', name.trim());
    body.set('query', historyUrl(state, { baseUrl: '' }).replace(/^\?/, ''));
    window.fetch(props.saveViewUrl || '/saved-views/create/', {
      method: 'POST',
      headers: { 'X-CSRFToken': props.model?.csrfToken || '' },
      body,
    }).then(response => response.json())
      .then(data => { if (data.url) window.location.assign(data.url); })
      .catch(() => {});
  }

  return <HistoryFeed
    model={props.model}
    labels={props.labels}
    palette={palette}
    onNavigate={navigate}
    onLoadMore={loadMore}
    onLoadDay={loadDay}
    onOpenEntry={openEntry}
    onEditEntry={editEntry}
    onDeleteEntry={deleteEntry}
    onApplyFilters={applyFilters}
    onClearFilters={clearFilters}
    onSaveView={saveView}
    onRetry={() => assign(props.baseUrl || window.location.pathname)} />;
}

export function mountHistoryFeed(host, props) {
  return mountRoot(host, <Adapter host={host} props={props} />);
}
