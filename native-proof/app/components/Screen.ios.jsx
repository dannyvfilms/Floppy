import React from 'react';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen as SharedScreen } from './Screen.jsx';
import { horizontalContentPadding } from '../safeAreaSpacing.mjs';

export { Section } from './Screen.jsx';

// The safe area already contributes to the distance from the screen edge.
export function Screen({ contentStyle, ...props }) {
  const insets = useSafeAreaInsets();
  return <SharedScreen {...props} contentStyle={[horizontalContentPadding(insets, 22), contentStyle]} />;
}
