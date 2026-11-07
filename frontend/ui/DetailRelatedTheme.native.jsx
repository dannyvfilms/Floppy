import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { DetailRelated } from './DetailRelated';

// Native counterpart for the browser detail-related theme adapter.
export function DetailRelatedTheme(props) {
  return <DetailRelated {...props} />;
}
