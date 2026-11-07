import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { DetailComposition } from './DetailComposition';

// Native counterpart for the browser detail composition theme adapter.
export function DetailCompositionTheme(props) {
  return <DetailComposition {...props} />;
}
