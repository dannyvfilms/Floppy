import React from 'react';
import { mountRoot } from '../settings/root';
import { Button } from './controls';

// The server wrote the same <button>; React replaces it, so htmx has to be told about the new node.
export function mountButton(host, { label, type, attrs, ...props }) {
  const unmount = mountRoot(host, <Button flat type={type} {...attrs} {...props}>{label}</Button>);
  if (Object.keys(attrs).some(name => name.startsWith('hx-'))) window.htmx?.process(host);
  return unmount;
}
