import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { Icon } from '../ui/Icon';
import { RatingStarIcon } from '../ui/RatingStarIcon.web';
import { RatingStars } from '../ui/RatingStars';
import {
  DiscoverFeedback,
  DiscoverHidden,
  DiscoverPreview,
  DiscoverRow,
  DiscoverState,
  DiscoverTabs,
} from './DiscoverScreen';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-accent)',
  accentText: '#ffffff',
  warning: 'var(--color-warning-text)',
  success: 'var(--color-status-clean)',
  danger: 'var(--color-error-text)',
  arrow: 'var(--color-text-secondary)',
  arrowDisabled: 'var(--color-surface-muted)',
  loading: 'var(--color-accent)',
  focus: 'var(--color-accent)',
  star: 'var(--color-warning-text)',
};

function navigate(href) {
  if (href) window.location.assign(href);
}

function renderActionIcon(action) {
  return action?.icon ? <Icon spec={action.icon} /> : null;
}

function renderRating({ value, label, scaleMax, palette: ratingPalette, onSelect }) {
  return <RatingStars scaleMax={scaleMax} value={value} label={label}
    onSelect={onSelect} palette={ratingPalette} renderStar={lit => RatingStarIcon(lit)} />;
}

function useActionHandler(props) {
  return (_model, action) => {
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
        headers: { 'X-CSRFToken': action.csrfToken || props.csrfToken || '' },
      });
    }
  };
}

function useRateHandler() {
  return (model, score) => {
    const rating = model?.rating;
    if (!rating?.rateUrl) return;
    window.htmx?.ajax('POST', rating.rateUrl, {
      swap: 'none',
      headers: { 'X-CSRFToken': model.csrfToken || '' },
      values: { score: score ?? rating.value, toggle: true },
    });
  };
}

function cardProps(props) {
  const onAction = useActionHandler(props);
  const onRate = useRateHandler();
  return {
    palette,
    labels: props.labels,
    onOpenCard: navigate,
    onOpenLink: navigate,
    onAction,
    onRate,
    renderRating,
    renderActionIcon,
  };
}

export function mountDiscoverRow(host, props) {
  const CardProps = cardProps(props);
  return mountRoot(host, <DiscoverRow row={props.row} palette={palette}
    labels={props.labels} {...CardProps} />);
}

export function mountDiscoverHidden(host, props) {
  const CardProps = cardProps(props);
  return mountRoot(host, <DiscoverHidden entries={props.entries}
    count={props.count} palette={palette} labels={props.labels} {...CardProps} />);
}

export function mountDiscoverPreview(host, props) {
  const CardProps = cardProps(props);
  return mountRoot(host, <DiscoverPreview row={props.row} palette={palette}
    labels={props.labels} {...CardProps} />);
}

export function mountDiscoverState(host, props) {
  return mountRoot(host, <DiscoverState kind={props.kind} palette={palette}
    labels={props.labels} />);
}

function Tabs({ host, props }) {
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    const Alpine = window.Alpine;
    if (!Alpine) return undefined;
    const runner = Alpine.effect(() => setSelected(Alpine.$data(host).selectedMedia));
    return () => Alpine.release(runner);
  }, [host]);
  return <DiscoverTabs items={props.items} selected={selected} label={props.label}
    palette={palette} onSelect={value => window.Alpine?.$data(host).switchMedia(value)} />;
}

export function mountDiscoverTabs(host, props) {
  return mountRoot(host, <Tabs host={host} props={props} />);
}

function feedbackState(data) {
  return {
    refreshing: Boolean(data?.refreshing),
    cacheRefreshing: Boolean(data?.cacheRefreshing),
    refreshStatus: {
      visible: Boolean(data?.refreshStatusVisible),
      message: data?.refreshStatusMessage || '',
    },
    toast: {
      visible: Boolean(data?.toastVisible),
      message: data?.toastMessage || '',
      undoToken: data?.undoToken || '',
    },
  };
}

function Feedback({ host, props }) {
  const [state, setState] = useState(() => feedbackState(window.Alpine?.$data(host)));
  useEffect(() => {
    const Alpine = window.Alpine;
    if (!Alpine) return undefined;
    const runner = Alpine.effect(() => setState(feedbackState(Alpine.$data(host))));
    return () => Alpine.release(runner);
  }, [host]);
  useEffect(() => {
    if (!host) return;
    const visible = state.refreshing || state.cacheRefreshing
      || state.refreshStatus.visible || state.toast.visible;
    host.style.display = visible ? '' : 'none';
  }, [host, state]);
  const data = window.Alpine?.$data(host);
  return <DiscoverFeedback {...state} labels={props.labels} palette={palette}
    toastStyle={{ position: 'fixed', top: 96, left: 0, right: 0, zIndex: 50, marginHorizontal: 16 }}
    onDismissRefreshStatus={() => data?.dismissRefreshStatus?.()}
    onDismissToast={() => data?.dismissToast?.()}
    onUndo={() => data?.undoAction?.()} />;
}

export function mountDiscoverFeedback(host, props) {
  return mountRoot(host, <Feedback host={host} props={props} />);
}
