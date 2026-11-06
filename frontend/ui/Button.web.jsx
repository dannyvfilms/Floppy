import React from 'react';
import { Icon } from './Icon';

function buttonClasses({ tone, small, auto, flat, danger, secondary }) {
  let classes = 'ui-button';
  if (flat) classes += ' ui-button-flat';
  if (danger) classes += ' ui-button-danger';
  if (secondary) classes += ' ui-button-secondary';
  if (tone) classes += ` ui-button-tone-${tone}`;
  if (small) classes += ' ui-button-small';
  if (auto) classes += ' ui-button-auto';
  return classes;
}

/** Browser implementation for both the legacy button tag and the shared
 * React Native Button contract. Form, link and htmx props stay on the native
 * element; the shared `onPress`, busy and auto-width props map to it.
 */
export function Button({
  label,
  children,
  tone,
  small = false,
  auto = false,
  flat = false,
  danger = false,
  secondary = false,
  href,
  disabled = false,
  type = 'button',
  attrs = {},
  onPress,
  busy = false,
  width,
  size,
  accessibilityLabel,
  palette,
  icon,
  ...props
}) {
  const shared = width !== undefined || size !== undefined || onPress !== undefined || busy;
  const className = buttonClasses({
    tone,
    small: shared ? size !== 'base' : small,
    auto: shared ? width !== 'full' : auto,
    flat,
    danger,
    secondary,
  });
  const content = children ?? label;
  const shown = busy && typeof content === 'string' ? '…' : content;
  const body = icon ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.375em' }}>
    <span style={{ display: 'inline-flex', fontSize: '1em' }}><Icon spec={icon} /></span>
    {shown}
  </span> : shown;
  const onClick = onPress || props.onClick;
  const { onClick: _legacyClick, ...rest } = props;
  const sharedStyle = shared
    ? {
      ...(tone === 'surface' ? { borderColor: 'var(--color-surface-border)' } : {}),
      ...(palette?.radius ? { borderRadius: palette.radius } : {}),
    }
    : undefined;
  const common = {
    className,
    style: sharedStyle,
    'aria-label': accessibilityLabel,
    'aria-busy': busy || undefined,
    onClick,
    ...attrs,
    ...rest,
  };
  if (href) return <a href={href} {...common}>{body}</a>;
  return <button type={type} disabled={disabled} {...common}>{body}</button>;
}
