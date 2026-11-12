import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { DeviceConnectCard } from './DeviceConnect';
import { copyText } from './clipboard';

const palette = {
  surface: 'var(--color-surface)',
  codeBackground: 'var(--color-sidebar)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  border: 'var(--color-surface-border)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceHover: 'var(--color-surface-hover)',
  accent: 'var(--color-accent)',
  accentContrast: '#ffffff',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  danger: 'var(--color-error-text)',
  radius: 6,
  focusStyle: {},
};

function Adapter({ props }) {
  const [state, setState] = useState('waiting');
  const [error, setError] = useState('');

  useEffect(() => {
    if (state !== 'waiting' || !props.pollUrl) return undefined;
    let active = true;
    let polling = false;

    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const response = await fetch(props.pollUrl, {
          headers: { Accept: 'text/html' },
          credentials: 'same-origin',
        });
        if (!active) return;
        const redirect = response.headers.get('HX-Redirect');
        if (redirect) {
          window.location.assign(redirect);
          return;
        }
        if (response.status !== 204 && !response.ok) {
          setError(`Authorization check failed (${response.status}).`);
        } else {
          setError('');
        }
      } catch (pollError) {
        if (active) setError('Could not reach Floppy. Checking again shortly.');
      } finally {
        polling = false;
      }
    };

    const interval = Math.max(1, Number(props.interval) || 5) * 1000;
    const timer = setInterval(poll, interval);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [props.pollUrl, props.interval, state]);

  return <DeviceConnectCard
    code={props.code}
    title={props.title}
    description={props.description}
    state={state}
    error={error}
    labels={props.labels}
    palette={palette}
    onCopy={copyText}
    onOpen={() => {
      if (props.openUrl) window.open(props.openUrl, '_blank', 'noopener,noreferrer');
    }}
    onCancel={() => {
      if (props.cancelUrl) window.location.assign(props.cancelUrl);
    }}
    onRetry={() => {
      if (props.cancelUrl) window.location.assign(props.cancelUrl);
    }} />;
}

export function mountDeviceConnect(host, props) {
  return mountRoot(host, <Adapter props={props} />);
}
