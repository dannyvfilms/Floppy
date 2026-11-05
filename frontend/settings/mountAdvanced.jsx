import React from 'react';
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
  accentStrong: 'var(--color-accent)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  danger: 'var(--color-error-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  radius: 6,
  fontFamily: 'inherit',
  focusStyle: {},
};

function submitForm(url, csrfToken, fields = {}) {
  const form = document.createElement('form');
  form.method = 'post';
  form.action = url;
  Object.entries({ csrfmiddlewaretoken: csrfToken, ...fields })
    .forEach(([name, value]) => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = value == null ? '' : String(value);
      form.append(input);
    });
  document.body.append(form);
  form.submit();
}

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}

function AdvancedAdapter({ props }) {
  const labels = props.labels || {};
  const submit = (url, fields) => submitForm(url, props.csrfToken, fields);
  return <>
    <LogsCard isSuperuser={props.isSuperuser}
      logsSince={props.logsSince}
      lastUncleanExit={props.lastUncleanExit}
      bugReportUrl={props.bugReportUrl}
      onDownloadLogs={() => window.location.assign(props.urls.logs)}
      onOpenUrl={openUrl}
      palette={systemPalette}
      labels={labels.logs} />
    <ImageCacheCard isSuperuser={props.isSuperuser}
      enabled={props.imageEnabled}
      count={props.imageCount}
      size={props.imageSize}
      onSave={enabled => submit(props.urls.updateImageCache, {
        image_caching_enabled: enabled ? '1' : '',
      })}
      onClear={() => {
        submit(props.urls.clearImageCache);
        return Promise.resolve();
      }}
      palette={systemPalette}
      labels={labels.imageCache} />
    <CacheManagementCard
      onClear={kind => {
        submit(props.urls.clearCaches[kind]);
        return Promise.resolve();
      }}
      palette={systemPalette}
      labels={labels.cache} />
  </>;
}

function ServerPortAdapter({ props }) {
  return <ServerPortCard {...props}
    onSave={port => submitForm(props.urls.update, props.csrfToken, {
      action: 'save',
      port,
    })}
    onReset={() => submitForm(props.urls.update, props.csrfToken, {
      action: 'reset',
    })}
    palette={systemPalette} />;
}

export function mountAdvanced(host, props) {
  return mountRoot(host, <AdvancedAdapter props={props} />);
}

export function mountServerPort(host, props) {
  return mountRoot(host, <ServerPortAdapter props={props} />);
}
