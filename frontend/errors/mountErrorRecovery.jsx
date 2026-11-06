import React from 'react';
import { mountRoot } from '../settings/root';
import { ErrorRecovery } from './ErrorRecovery';
import { Icon } from '../ui/Icon';
import { copyText } from '../ui/clipboard.web';

const palette = {
  background: 'var(--color-page-bg)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-link)',
  accentStrong: 'var(--color-accent)',
  danger: 'var(--color-error-text)',
  focusStyle: {},
};

const iconRoot = {
  fill: 'none',
  stroke: 'currentColor',
  'stroke-width': 2,
  'stroke-linecap': 'round',
  'stroke-linejoin': 'round',
};

const iconShapes = {
  copy: [
    { tag: 'rect', attrs: { x: '9', y: '9', width: '13', height: '13', rx: '2', ry: '2' }, children: [] },
    { tag: 'path', attrs: { d: 'M5 15V5a2 2 0 0 1 2-2h10' }, children: [] },
  ],
  copied: [
    { tag: 'polyline', attrs: { points: '20 6 9 17 4 12' }, children: [] },
  ],
  home: [
    { tag: 'path', attrs: { d: 'm3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' }, children: [] },
    { tag: 'polyline', attrs: { points: '9 22 9 12 15 12 15 22' }, children: [] },
  ],
  login: [
    { tag: 'rect', attrs: { width: '18', height: '11', x: '3', y: '11', rx: '2', ry: '2' }, children: [] },
    { tag: 'path', attrs: { d: 'M7 11V7a5 5 0 0 1 10 0v4' }, children: [] },
  ],
  retry: [
    { tag: 'path', attrs: { d: 'M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' }, children: [] },
    { tag: 'path', attrs: { d: 'M3 3v5h5' }, children: [] },
    { tag: 'path', attrs: { d: 'M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16' }, children: [] },
    { tag: 'path', attrs: { d: 'M16 16h5v5' }, children: [] },
  ],
  support: [
    { tag: 'path', attrs: { d: 'M15 3h6v6' }, children: [] },
    { tag: 'path', attrs: { d: 'M10 14 21 3' }, children: [] },
    { tag: 'path', attrs: { d: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' }, children: [] },
  ],
};

function glyph(name, color, size = 20) {
  return <span style={{ display: 'inline-flex', flex: 'none', width: size, height: size, fontSize: size, color }}>
    <Icon spec={{ viewBox: '0 0 24 24', root: iconRoot, children: iconShapes[name] }} />
  </span>;
}

const icons = {
  copy: glyph('copy', 'var(--color-text-muted)'),
  copied: glyph('copied', '#34d399'),
  homePrimary: glyph('home', '#ffffff'),
  homeSurface: glyph('home', 'var(--color-text)'),
  login: glyph('login', '#ffffff'),
  retry: glyph('retry', '#ffffff'),
  support: glyph('support', '#fde68a', 16),
};

function assign(href) {
  if (href) window.location.assign(href);
}

function openExternal(href) {
  if (href) window.open(href, '_blank', 'noopener,noreferrer');
}

function ErrorRecoveryAdapter({ props }) {
  const actions = props.actions || {};
  const support = props.support
    ? { ...props.support, onOpen: () => openExternal(props.support.href) }
    : undefined;
  return <ErrorRecovery
    status={props.status}
    heading={props.heading}
    message={props.message}
    checks={props.checks}
    support={support}
    report={props.report}
    reportTitle={props.reportTitle}
    reportNote={props.reportNote}
    labels={props.labels}
    icons={icons}
    statusSize={128}
    palette={palette}
    onCopyReport={copyText}
    onReportIssue={actions.reportIssueHref ? () => openExternal(actions.reportIssueHref) : undefined}
    onRetry={actions.retryHref ? () => assign(actions.retryHref) : undefined}
    onLogin={actions.loginHref ? () => assign(actions.loginHref) : undefined}
    onGoHome={actions.homeHref ? () => assign(actions.homeHref) : undefined}
  />;
}

export function mountErrorRecovery(host, props) {
  return mountRoot(host, <ErrorRecoveryAdapter props={props} />);
}
