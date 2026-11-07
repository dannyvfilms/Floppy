import React from 'react';
import { Screen as SharedScreen } from './Screen.jsx';

export { Section } from './Screen.jsx';

// The iOS system rail already excludes and pads its controls from this canvas.
export function Screen({ contentStyle, ...props }) {
  return <SharedScreen {...props} contentStyle={[{ paddingLeft: 22, paddingRight: 0 }, contentStyle]} />;
}
