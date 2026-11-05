import React from 'react';

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
  palette: _palette,
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
  const onClick = onPress || props.onClick;
  const { onClick: _legacyClick, ...rest } = props;
  const sharedStyle = shared && tone === 'surface'
    ? { borderColor: 'var(--color-surface-border)' }
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
  if (href) return <a href={href} {...common}>{shown}</a>;
  return <button type={type} disabled={disabled} {...common}>{shown}</button>;
}
