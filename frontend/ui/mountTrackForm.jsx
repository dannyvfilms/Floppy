import React, { useEffect, useMemo, useRef, useState } from 'react';
import { mountRoot } from '../settings/root';
import { TrackDialog } from './TrackDialog';
import { initialTrackValues, normalizeTrackForm } from './mediaCardForms';

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
  const palette = {
    text: color('--color-text', '#fafafa'),
    textSecondary: color('--color-text-secondary', '#d4d4d8'),
    textMuted: color('--color-text-muted', '#a1a1aa'),
    surface: color('--color-surface', '#27272a'),
    surfaceStrong: color('--color-surface-strong', '#3f3f46'),
    surfaceMuted: color('--color-surface-muted', '#52525b'),
    border: color('--color-surface-border', '#3f3f46'),
    accent: color('--color-accent', '#6366f1'),
    accentStrong: color('--color-accent-strong', '#4f46e5'),
    accentContrast: '#ffffff',
    link: color('--color-link', '#818cf8'),
    danger: color('--color-danger', '#ef4444'),
    radius: 8,
    radiusSmall: 6,
    focusStyle: {},
  };
  palette.dateTime = {
    ...palette,
    radius: 8,
    radiusSmall: 6,
  };
  palette.rating = {
    lit: '#f59e0b',
    unlit: palette.surfaceMuted,
    muted: palette.textMuted,
    focusStyle: {},
  };
  return palette;
}

function Adapter({ host, props }) {
  const model = useMemo(() => normalizeTrackForm(props?.model || {}), [props]);
  const initialValues = useMemo(() => initialTrackValues(model), [model]);
  const [values, setValues] = useState(initialValues);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState('');
  const [palette, setPalette] = useState(readPalette);
  const startCleared = useRef(false);

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

  const legacyForm = () => document.getElementById(model.formId);

  useEffect(() => {
    const nodes = [legacyForm(), ...(model.legacyIds || []).map(id => document.getElementById(id))]
      .filter(Boolean);
    const previous = nodes.map(node => node.style.display);
    nodes.forEach(node => { node.style.display = 'none'; });
    return () => { nodes.forEach((node, index) => { node.style.display = previous[index]; }); };
  }, [model.formId, model.legacyIds]);

  function change(name, value) {
    setValues(current => ({ ...current, [name]: value }));
    if (name === 'start_date') {
      startCleared.current = !value && Boolean(values.start_date);
      if (value) startCleared.current = false;
    }
  }

  function send(url, extra = {}, submitted = values) {
    const ajax = window.htmx?.ajax;
    if (!ajax || !url) return;
    const body = {
      ...(model.hidden || {}),
      ...submitted,
      csrfmiddlewaretoken: model.csrfToken || '',
      ...extra,
    };
    if (startCleared.current && 'start_date_cleared' in body) {
      body.start_date_cleared = '1';
    }
    const target = (model.target && document.querySelector(model.target))
      || legacyForm()
      || host;
    setBusy(true);
    setServerError('');
    const request = ajax('POST', url, {
      values: body,
      target,
      swap: model.swap || 'none',
    });
    if (request?.finally) request.finally(() => setBusy(false));
    else setBusy(false);
  }

  const labels = model.labels || {};

  return <TrackDialog
    embedded
    open
    model={model}
    values={values}
    errors={props?.errors || {}}
    status="ready"
    serverError={serverError}
    busy={busy}
    labels={labels}
    palette={palette}
    tabs={[]}
    onChange={change}
    onSubmit={next => send(model.action, {}, next)}
    onDelete={next => send(model.deleteAction, {}, next)}
    onRewatch={(action, next) => send(model.repeatIdentity?.rewatchUrl, {}, next)}
    onSaveAsNew={next => send(model.action, { save_as_new_entry: '1' }, next)}
    onSecondaryAction={(action, next) => send(action.url, action.body || {}, next)}
    onRetry={() => setServerError('')}
    onClose={() => window.closeTrackModal?.(legacyForm() || host)} />;
}

export function mountTrackForm(host, props) {
  if (!window.htmx?.ajax) return () => {};
  return mountRoot(host, <Adapter host={host} props={props} />);
}
