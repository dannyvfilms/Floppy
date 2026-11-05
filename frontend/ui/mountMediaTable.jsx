import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { MediaTable } from './MediaTable';
import { MediaColumnMenu } from './ColumnMenu';

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
    warning: '#f59e0b',
    success: '#10b981',
    danger: color('--color-danger', '#ef4444'),
  };
}

function usePalette() {
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
  return palette;
}

function descendingDefault(key, ascending) {
  return ascending.includes(key) ? 'asc' : 'desc';
}

function TableAdapter({ props }) {
  const palette = usePalette();
  const [rows, setRows] = useState(() => props.table.rows || []);
  const [nextUrl, setNextUrl] = useState(props.table.nextUrl || '');
  const [loadingMore, setLoadingMore] = useState(false);

  function sortBy(key) {
    const url = new URL(window.location.href);
    const currentSort = props.table.sort;
    const currentDirection = props.table.sortDirection;
    const direction = currentSort === key
      ? (currentDirection === 'asc' ? 'desc' : 'asc')
      : descendingDefault(key, props.sorts?.ascending || []);
    url.searchParams.set('sort', key);
    url.searchParams.set('direction', direction);
    url.searchParams.delete('page');
    window.location.assign(url.toString());
  }

  async function loadMore() {
    if (!nextUrl || loadingMore) return;
    setLoadingMore(true);
    try {
      const response = await window.fetch(nextUrl, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`Table page failed: ${response.status}`);
      const payload = await response.json();
      setRows(current => [...current, ...(payload.rows || [])]);
      setNextUrl(payload.nextUrl || '');
    } catch (error) {
      window.location.assign(nextUrl);
    } finally {
      setLoadingMore(false);
    }
  }

  return <MediaTable
    columns={props.table.columns || []}
    rows={rows}
    sort={props.table.sort}
    sortDirection={props.table.sortDirection}
    onSort={sortBy}
    onOpen={row => row.href && window.location.assign(row.href)}
    onOpenLink={href => href && window.location.assign(href)}
    hasMore={!!nextUrl}
    loadingMore={loadingMore}
    onLoadMore={loadMore}
    palette={palette} />;
}

function MenuAdapter({ props }) {
  const palette = usePalette();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function save({ order, hidden }) {
    if (saving) return;
    setSaving(true);
    setError('');
    const body = new URLSearchParams();
    body.set('table_type', props.menu.tableType || 'media');
    if (props.menu.mediaTypeKey) body.set('media_type_key', props.menu.mediaTypeKey);
    body.set('sort', props.menu.sort || '');
    body.set('order', JSON.stringify(order));
    body.set('hidden', JSON.stringify(hidden));
    try {
      const response = await window.fetch(props.menu.updateUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': props.menu.csrfToken,
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body,
      });
      if (!response.ok) throw new Error(`Column save failed: ${response.status}`);
      window.location.reload();
    } catch (failure) {
      setSaving(false);
      setError('Columns could not be saved. Try again.');
    }
  }

  return <MediaColumnMenu
    columns={props.menu.columns || []}
    defaultOrder={props.menu.defaultOrder || []}
    defaultHidden={props.menu.defaultHidden || []}
    disabled={saving}
    palette={palette}
    onSave={save}
    labels={error ? { reset: error } : undefined} />;
}

export function mountMediaTable(host, props) {
  if (host.matches('[data-media-column-menu-root]')) {
    return mountRoot(host, <MenuAdapter props={props} />);
  }
  return mountRoot(host, <TableAdapter props={props} />);
}
