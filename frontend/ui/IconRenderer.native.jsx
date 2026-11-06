import React from 'react';
import { View } from 'react-native';
import { Icon as SharedIcon } from './Icon';

// Native counterpart for the web SVG renderer. Native uses the universal text
// glyph fallback; this wrapper keeps the platform-pair contract explicit.
export function Icon(props) {
  return <View><SharedIcon {...props} /></View>;
}
