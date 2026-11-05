import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { Icon } from './Icon';
import { MediaCard } from './MediaCard';
import { RatingStarIcon } from './RatingStarIcon.web';
import { RatingStars } from './RatingStars';

const PALETTE = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-accent)',
  link: 'var(--color-link)',
  star: 'var(--color-warning-text)',
  card: 'var(--color-surface)',
  chipBackground: 'rgba(24, 24, 27, 0.92)',
  chipText: '#ffffff',
  placeholder: 'var(--color-surface-strong)',
  progressTrack: 'rgba(24, 24, 27, 0.6)',
  progressFill: 'var(--color-accent)',
  progressPaused: 'rgba(99, 102, 241, 0.4)',
  overlay: 'rgba(0, 0, 0, 0.5)',
  actionText: '#ffffff',
  actionTones: {
    indigo: '#4f46e5',
    emerald: '#059669',
    amber: '#d97706',
    rose: '#e11d48',
  },
  reorder: 'rgba(79, 70, 229, 0.95)',
  local: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: 'rgba(245, 158, 11, 0.3)',
    color: '#fde68a',
  },
  statusColors: {
    Completed: '#10b981',
    'In progress': '#6366f1',
    Paused: '#f97316',
    Planning: '#38bdf8',
    Dropped: '#ef4444',
  },
  rating: { lit: '#facc15', unlit: '#52525b', muted: 'var(--color-text-muted)', focusStyle: {} },
};

function navigate(href) {
  if (href) window.location.assign(href);
}

// Bulk selection lives in the page's Alpine scope (selectMode, isItemSelected,
// toggleItemSelected). Mirror it here instead of keeping a second copy.
function useSelection(host, itemId) {
  const [state, setState] = useState({ active: false, selected: false });
  useEffect(() => {
    const Alpine = window.Alpine;
    if (itemId == null || !Alpine) return undefined;
    const runner = Alpine.effect(() => {
      const scope = Alpine.$data(host);
      setState({ active: !!scope.selectMode, selected: !!scope.isItemSelected?.(itemId) });
    });
    return () => Alpine.release(runner);
  }, [host, itemId]);
  if (itemId == null) return undefined;
  return { ...state, toggle: () => window.Alpine?.$data(host).toggleItemSelected(itemId) };
}

// Save and score responses still swap server fragments out of band for pages
// that render them. A card React owns ignores that swap and listens for the
// floppyCardUpdate event the same responses send.
function liveChip(chip, live, labels) {
  if (!live) return chip;
  if (live.statusless) return { kind: 'no-status', label: labels.noStatus, hideOnMobile: chip?.hideOnMobile };
  if (live.status) {
    if (chip?.kind === 'event') return chip;
    return { kind: 'status', status: live.status, label: chip?.label, hideOnMobile: chip?.hideOnMobile };
  }
  return chip?.kind === 'event' ? chip : null;
}

function useLiveModel(model, labels) {
  const [live, setLive] = useState(null);
  useEffect(() => {
    if (!model.cardKey) return undefined;
    const onUpdate = (event) => {
      if (event.detail?.cardKey === model.cardKey) setLive(event.detail);
    };
    document.addEventListener('floppyCardUpdate', onUpdate);
    return () => document.removeEventListener('floppyCardUpdate', onUpdate);
  }, [model.cardKey]);
  if (!live) return model;
  return {
    ...model,
    statusChip: liveChip(model.statusChip, live, labels),
    rating: live.rating ? { ...model.rating, ...live.rating } : model.rating,
  };
}

function renderActionIcon(action) {
  return action?.icon ? <Icon spec={action.icon} /> : null;
}

function renderRating({ value, label, scaleMax, palette, onSelect }) {
  return <RatingStars scaleMax={scaleMax} value={value} label={label}
    onSelect={onSelect} palette={palette} renderStar={lit => RatingStarIcon(lit)} />;
}

function runAction(model, action) {
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
      swap: action.swap || 'innerHTML',
      values: action.vals,
      headers: { 'X-CSRFToken': action.csrfToken || model.csrfToken || '' },
    });
  }
}

function rateCard(model, score) {
  const rating = model?.rating;
  if (!rating?.rateUrl) return;
  window.htmx?.ajax('POST', rating.rateUrl, {
    swap: 'none',
    headers: { 'X-CSRFToken': model.csrfToken || '' },
    values: { score: score ?? rating.value, toggle: true },
  });
}

function reorder(model, step) {
  const actions = model.actions;
  const form = document.getElementById('filter-form');
  const values = {
    ...(form ? Object.fromEntries(new FormData(form)) : {}),
    item_id: String(actions.ordering.itemId),
    action: step,
  };
  const indicator = document.getElementById('loading-indicator');
  indicator?.classList.add('htmx-request');
  window.htmx?.ajax('POST', actions.ordering.url, {
    swap: 'none',
    values,
    headers: { 'X-CSRFToken': actions.csrfToken },
  })?.then(() => window.refreshCustomListGrid?.())
    .finally(() => indicator?.classList.remove('htmx-request'));
}

export function MediaCardWeb({
  host,
  model,
  labels,
  selection,
  readOnly = false,
  width = '100%',
  onOpen,
}) {
  const liveModel = useLiveModel(model, labels);
  return <MediaCard
    model={liveModel}
    labels={labels}
    palette={PALETTE}
    selection={selection}
    readOnly={readOnly}
    width={width}
    onOpen={() => (onOpen ? onOpen() : navigate(liveModel.href))}
    onOpenLink={navigate}
    onAction={action => runAction(liveModel, action)}
    onRate={score => rateCard(liveModel, score)}
    onReorder={liveModel.actions?.ordering ? step => reorder(liveModel, step) : undefined}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon} />;
}

function Card({ host, props }) {
  const selection = useSelection(host, props.model.bulkItemId);
  return <MediaCardWeb
    host={host}
    model={props.model}
    labels={props.labels}
    selection={selection}
    readOnly={!!props.model.publicView} />;
}

export function mountMediaCard(host, props) {
  const restore = mountRoot(host, <Card host={host} props={props} />);
  // The release-year loader runs once per page or swap, often before this mount.
  window.loadVisibleReleaseYears?.();
  return () => { restore(); };
}
