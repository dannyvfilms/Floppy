import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import Svg, {
  Circle,
  Ellipse,
  G,
  Line,
  Path,
  Polygon,
  Polyline,
  Rect,
} from 'react-native-svg';

// Icons arrive as parsed shapes from the server, never as markup. This is the
// native counterpart of IconRenderer.web.jsx: the same shapes, drawn with
// react-native-svg so the sidebar and settings show the web icons rather than
// a first-letter fallback.
const TAGS = {
  path: Path,
  circle: Circle,
  rect: Rect,
  line: Line,
  polyline: Polyline,
  polygon: Polygon,
  ellipse: Ellipse,
  g: G,
};

const ATTRS = {
  'stroke-width': 'strokeWidth',
  'stroke-linecap': 'strokeLinecap',
  'stroke-linejoin': 'strokeLinejoin',
  'stroke-dasharray': 'strokeDasharray',
  'stroke-dashoffset': 'strokeDashoffset',
  'fill-rule': 'fillRule',
  'clip-rule': 'clipRule',
};

function convert(node, color) {
  const out = {};
  Object.entries(node?.attrs || {}).forEach(([key, value]) => {
    if (!value || key === 'class' || key === 'style') return;
    const name = ATTRS[key] || key;
    out[name] = value === 'currentColor' ? color : value;
  });
  return out;
}

function Shape({ node, color }) {
  const Component = TAGS[node.tag];
  if (!Component) return null;
  const children = node.children?.length
    ? node.children.map((child, index) => <Shape key={index} node={child} color={color} />)
    : null;
  return <Component {...convert(node, color)}>{children}</Component>;
}

export function Icon({ spec, color = '#a1a1aa', size = 20 }) {
  if (!spec?.children) return null;
  const root = convert({ attrs: spec.root }, color);
  return <Svg width={size} height={size} viewBox={spec.viewBox || '0 0 24 24'}
    fill={root.fill || 'none'}
    stroke={root.stroke || 'none'}
    strokeWidth={root.strokeWidth || 2}
    strokeLinecap={root.strokeLinecap || 'round'}
    strokeLinejoin={root.strokeLinejoin || 'round'}>
    {spec.children.map((child, index) => <Shape key={index} node={child} color={color} />)}
  </Svg>;
}