import React from 'react';
import { setIconRenderer } from '../../frontend/ui/Icon';
import { Icon } from '../../frontend/ui/IconRenderer.native';

// Shared components call the universal Icon contract. Native installs the SVG
// renderer once, so every icon a server model carries draws as the same shape
// the web draws.
export function renderNativeIcon(spec, options = {}) {
  return <Icon spec={spec} color={options.color} size={options.size} />;
}

export function installNativeIconRenderer() {
  setIconRenderer(renderNativeIcon);
}