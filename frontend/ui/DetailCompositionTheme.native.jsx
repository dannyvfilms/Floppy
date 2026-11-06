import React from 'react';
import { View } from 'react-native';
import { DetailComposition } from './DetailComposition';

// Native counterpart for the browser detail composition theme adapter.
export function DetailCompositionTheme(props) {
  return <View><DetailComposition {...props} /></View>;
}
