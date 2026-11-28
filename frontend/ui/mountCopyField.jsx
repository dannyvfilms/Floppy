import React, { useEffect } from 'react';
import { View } from 'react-native';
import { mountRoot } from '../settings/root';
import { CopyField } from './CopyField';
import { copyText } from './clipboard.web';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  success: 'var(--color-status-clean)',
  danger: 'var(--color-error-text)',
  link: 'var(--color-link)',
  // The server control's check is Tailwind `text-emerald-400`.
  copiedIcon: 'var(--color-emerald-400, #34d399)',
  radius: 8,
  focusStyle: {},
};

const buttonPalette = {
  primary: {
    background: 'var(--color-accent)',
    pressed: 'var(--color-accent-strong)',
    hovered: 'var(--color-accent-strong)',
    text: '#ffffff',
    border: 'transparent',
  },
  surface: {
    background: 'var(--color-surface-strong)',
    pressed: 'var(--color-surface-muted)',
    hovered: 'var(--color-surface-muted)',
    text: 'var(--color-text)',
    border: 'var(--color-surface-border)',
  },
  radius: 6,
  focusStyle: {},
};

// Moves the server-rendered input into the field, like the settings page's
// ServerContent: the credential stays in that DOM node and never enters props.
// Clicking it selects the whole value, as copy-item.js does for the server
// control (whose data-copy-target marker is gone while React owns the field),
// so manual copying keeps working after a failed copy.
function InputSlot({ node }) {
  useEffect(() => {
    const selectAll = () => node.select();
    node.addEventListener('click', selectAll);
    return () => node.removeEventListener('click', selectAll);
  }, [node]);
  const attach = element => {
    if (element && node.parentNode !== element) element.appendChild(node);
  };
  return <View ref={attach} style={{ minWidth: 0 }} />;
}

function CopyFieldAdapter({ props, input = null }) {
  if (!input) {
    return <CopyField {...props} onCopy={copyText}
      palette={palette} buttonPalette={buttonPalette} />;
  }
  // Credential fields (`credential: true`): the props carry labels only. The
  // value is read from the server input at copy time, so a token or one-time
  // secret is never serialized into the page props or a presentation model.
  return <CopyField {...props} value={undefined} valueSlot={<InputSlot node={input} />}
    disabled={!input.value} onCopy={() => copyText(input.value)}
    palette={palette} buttonPalette={buttonPalette} />;
}

export function mountCopyField(host, props) {
  const input = props?.credential ? host.querySelector('input') : null;
  return mountRoot(host, <CopyFieldAdapter props={props} input={input} />);
}
