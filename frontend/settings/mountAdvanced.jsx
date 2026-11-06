import React, { useState } from 'react';
import { View } from 'react-native';
import { mountRoot } from './root';
import {
  CacheManagementCard,
  ImageCacheCard,
  LogsCard,
  ServerPortCard,
} from './AdvancedSettings';

export const systemPalette = {
  background: 'var(--color-surface)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  surfaceHover: 'var(--color-surface-hover)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-link)',
  link: 'var(--color-link)',
  pageBackground: 'var(--color-page-bg)',
  accentStrong: 'var(--color-accent)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  danger: 'var(--color-error-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  radius: 'var(--theme-radius, 0.75rem)',
  fontFamily: 'inherit',
  focusStyle: {},
};

function formBody(fields = {}) {
  const body = new URLSearchParams();
  Object.entries(fields).forEach(([name, value]) => {
    if (value !== undefined && value !== null) body.append(name, String(value));
  });
  return body;
}

async function postJson(url, csrfToken, fields = {}) {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrfToken || '',
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: formBody(fields),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.message || data.error || 'The request failed.');
  }
  return data;
}

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}

function AdvancedAdapter({ props }) {
  const labels = props.labels || {};
  const [logs, setLogs] = useState({ busy: false, error: '', success: '' });
  const [image, setImage] = useState({
    enabled: Boolean(props.imageEnabled),
    count: props.imageCount,
    size: props.imageSize,
    busy: false,
    error: '',
    success: '',
  });
  const [cache, setCache] = useState({ busyKind: '', success: '' });

  function downloadLogs() {
    if (!props.urls.logs) return;
    setLogs({ busy: true, error: '', success: '' });
    window.location.assign(props.urls.logs);
    window.setTimeout(() => {
      setLogs(current => (current.busy
        ? { busy: false, error: '', success: '' }
        : current));
    }, 1500);
  }

  async function saveImage(enabled) {
    setImage(current => ({ ...current, busy: true, error: '', success: '' }));
    try {
      const data = await postJson(props.urls.updateImageCache, props.csrfToken, {
        image_caching_enabled: enabled ? '1' : '',
      });
      setImage(current => ({
        ...current,
        busy: false,
        enabled: data.imageEnabled ?? enabled,
        success: data.message || '',
      }));
    } catch (failure) {
      setImage(current => ({
        ...current,
        busy: false,
        error: failure.message || labels.imageCache?.saveError || '',
      }));
    }
  }

  async function clearImageCache() {
    setImage(current => ({ ...current, busy: true, error: '', success: '' }));
    try {
      const data = await postJson(props.urls.clearImageCache, props.csrfToken);
      setImage(current => ({
        ...current,
        count: data.imageCount ?? current.count,
        size: data.imageSize ?? current.size,
        success: data.message || '',
      }));
    } catch (failure) {
      setImage(current => ({ ...current, error: failure.message || '' }));
      throw failure;
    } finally {
      setImage(current => ({ ...current, busy: false }));
    }
  }

  async function clearCache(kind) {
    setCache({ busyKind: kind, success: '' });
    try {
      const data = await postJson(props.urls.clearCaches[kind], props.csrfToken);
      setCache({ busyKind: '', success: data.message || '' });
    } catch (failure) {
      setCache({ busyKind: '', success: '' });
      throw failure;
    }
  }

  return <View style={{ gap: 24, paddingBottom: 24 }}>
    <LogsCard isSuperuser={props.isSuperuser}
      logsSince={props.logsSince}
      lastUncleanExit={props.lastUncleanExit}
      bugReportUrl={props.bugReportUrl}
      busy={logs.busy} error={logs.error} success={logs.success}
      onDownloadLogs={downloadLogs}
      onOpenUrl={openUrl}
      palette={systemPalette}
      labels={labels.logs} icons={props.icons} />
    <ImageCacheCard isSuperuser={props.isSuperuser}
      enabled={image.enabled}
      count={image.count}
      size={image.size}
      busy={image.busy} error={image.error} success={image.success}
      onSave={saveImage}
      onClear={clearImageCache}
      palette={systemPalette}
      labels={labels.imageCache} icons={props.icons} />
    <CacheManagementCard
      busyKind={cache.busyKind} success={cache.success}
      onClear={clearCache}
      palette={systemPalette}
      labels={labels.cache} icons={props.icons} />
  </View>;
}

function ServerPortAdapter({ props }) {
  const [state, setState] = useState(props);
  const [status, setStatus] = useState({ busy: false, error: '', success: '' });

  async function write(action, fields = {}) {
    setStatus({ busy: true, error: '', success: '' });
    try {
      const data = await postJson(props.urls.update, props.csrfToken, {
        action,
        ...fields,
      });
      setState(current => ({ ...current, ...(data.serverPort || {}) }));
      setStatus({ busy: false, error: '', success: data.message || '' });
    } catch (failure) {
      setStatus({
        busy: false,
        error: failure.message || '',
        success: '',
      });
    }
  }

  return <ServerPortCard {...state}
    busy={status.busy} error={status.error} success={status.success}
    onSave={port => write('save', { port })}
    onReset={() => write('reset')}
    palette={systemPalette} />;
}

export function mountAdvanced(host, props) {
  return mountRoot(host, <AdvancedAdapter props={props} />);
}

export function mountServerPort(host, props) {
  return mountRoot(host, <ServerPortAdapter props={props} />);
}
