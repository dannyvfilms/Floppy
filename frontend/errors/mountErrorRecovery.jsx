import React from 'react';
import { mountRoot } from '../settings/root';
import { ErrorRecovery } from './ErrorRecovery';
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
    statusSize={96}
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
