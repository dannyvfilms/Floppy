import React, { useEffect, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { mountRoot } from '../settings/root';
import { DetailTrackSplit } from './DetailTrackSplit';

function Adapter({ host, actions }) {
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(null);
  const { width } = useWindowDimensions();
  useEffect(() => {
    const fallback = host.parentElement.querySelector('[data-track-split-fallback]');
    const updatePalette = () => {
      const css = getComputedStyle(document.documentElement);
      const token = (name, defaultValue) => css.getPropertyValue(name).trim() || defaultValue;
      setPalette({ accent: '#6366f1', accentStrong: '#4f46e5', hoveredAccent: '#4338ca', accentContrast: '#ffffff',
        surfaceStrong: token('--color-surface-strong', '#27272a'),
        surfaceMuted: token('--color-surface-hover', '#3f3f46'),
        border: token('--color-surface-border', '#52525b'),
        textSecondary: token('--color-text-secondary', '#d4d4d8') });
    };
    updatePalette();
    const observer = new MutationObserver(updatePalette);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    scheme.addEventListener('change', updatePalette);
    if (fallback) fallback.style.display = 'none';
    const dismiss = event => {
      if (event.type === 'keydown' ? event.key === 'Escape' : !host.contains(event.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => {
      if (fallback) fallback.style.display = '';
      observer.disconnect();
      scheme.removeEventListener('change', updatePalette);
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('keydown', dismiss);
    };
  }, [host]);
  if (!palette || !actions.length) return null;
  const run = action => {
    setOpen(false);
    host.parentElement.querySelector(`[data-track-split-fallback] [data-track-action-key="${action.key}"]`)?.click();
  };
  const icon = value => value === 'chevron-down' ? 'chevronDown' : value;
  const map = action => ({ ...action, icon: icon(action.icon),
    label: action.key === 'edit' && action === actions[0] ? host.dataset.statusLabel : action.label,
    onPress: () => run(action) });
  const rest = actions.slice(1);
  // Web keeps the anchored detail menu; native opens its existing adaptive sheet.
  const edit = rest.length > 1
    ? { label: host.dataset.moreLabel, icon: 'chevronDown', accessibilityState: { expanded: open }, onPress: () => setOpen(value => !value) }
    : rest.length ? { ...map(rest[0]), label: rest[0].key === 'edit' ? host.dataset.editLabel : rest[0].label } : null;
  return <DetailTrackSplit primary={map(actions[0])} edit={edit} palette={palette} inline={width >= 768} horizontalPadding={20} secondaryWidth={40} secondaryIconSize={16}
    menu={rest.length > 1 ? rest.map(map) : []} menuOpen={open} />;
}

export function mountDetailTrackSplit(host, props) {
  return mountRoot(host, <Adapter host={host} actions={props} />);
}
