import React from 'react';
import { Text } from 'react-native';

// Web installs an SVG renderer during island startup. Native, and any web
// surface that renders before that renderer is installed, falls back to a text
// glyph. Keeping this module universal is what lets shared settings/provider
// components use icons without importing a browser-only implementation.
let iconRenderer = null;

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
