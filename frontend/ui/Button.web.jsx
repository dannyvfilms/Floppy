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
  ...props
}) {
  const content = children ?? label;
  const className = buttonClasses({ tone, small, auto, flat, danger, secondary });
  if (href) return <a href={href} className={className} {...attrs} {...props}>{content}</a>;
  return <button type={type} className={className} disabled={disabled} {...attrs} {...props}>{content}</button>;
}
