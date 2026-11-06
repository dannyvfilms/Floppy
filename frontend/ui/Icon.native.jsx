import React from 'react';
import { Text } from 'react-native';

// Parsed SVG shapes are web-only. Native shows a glyph derived from the icon's
// label or name, and accepts children for a caller-supplied glyph.
const glyph = (spec) => {
  const label = spec?.label || spec?.name || '';
  return String(label).trim().charAt(0).toUpperCase() || '\u2022';
};

export function Icon({ spec, style, children }) {
  return <Text accessible={false} style={style}>{children ?? glyph(spec)}</Text>;
}
