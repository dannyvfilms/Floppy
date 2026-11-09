import React from 'react';
import { Text } from 'react-native';

// Web installs an SVG renderer during island startup. Native, and any web
// surface that renders before that renderer is installed, falls back to a text
// glyph. Keeping this module universal is what lets shared settings/provider
// components use icons without importing a browser-only implementation.
let iconRenderer = null;

// Same connected magnifier as app/icons/magnifying-glass.svg.
const searchSpec = {
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [
    { tag: 'circle', attrs: { cx: '11', cy: '11', r: '8' }, children: [] },
    { tag: 'path', attrs: { d: 'M21 21l-4.35-4.35' }, children: [] },
  ],
};

export function SearchIcon({ color, size = 20, style }) {
  return <Icon spec={searchSpec} color={color} size={size} style={style} />;
}

export function setIconRenderer(renderer) {
  iconRenderer = typeof renderer === 'function' ? renderer : null;
}

export function Icon({ spec, style, children, color, size }) {
  const rendered = iconRenderer ? iconRenderer(spec, { color, size }) : null;
  if (rendered !== null && rendered !== undefined) {
    return rendered;
  }
  const label = spec?.label || spec?.name || '';
  const glyph = String(label).trim().charAt(0).toUpperCase() || '\u2022';
  return <Text accessible={false} style={style}>{children ?? glyph}</Text>;
}
