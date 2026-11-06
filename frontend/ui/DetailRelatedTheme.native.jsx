import React from 'react';
import { View } from 'react-native';
import { DetailRelated } from './DetailRelated';

// Native counterpart for the browser detail-related theme adapter.
export function DetailRelatedTheme(props) {
  return <View><DetailRelated {...props} /></View>;
}
