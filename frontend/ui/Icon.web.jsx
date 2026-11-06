import React from 'react';

// Icons arrive as parsed shapes from the server, never as markup.
const camel = (name) => name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());

function Shape({ node }) {
  const props = {};
  for (const [name, value] of Object.entries(node.attrs)) if (name !== 'class') props[camel(name)] = value;
  return React.createElement(node.tag, props, ...node.children.map((child, index) => <Shape key={index} node={child} />));
}

export function Icon({ spec, className }) {
  return <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox={spec.viewBox}
    fill={spec.root.fill} stroke={spec.root.stroke} strokeWidth={spec.root['stroke-width']}
    strokeLinecap={spec.root['stroke-linecap']} strokeLinejoin={spec.root['stroke-linejoin']} className={className} aria-hidden="true">
    {spec.children.map((child, index) => <Shape key={index} node={child} />)}
  </svg>;
}
