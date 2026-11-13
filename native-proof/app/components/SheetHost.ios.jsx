import React from 'react';
import { BottomSheet } from '@expo/ui';
import { RNHostView } from '@expo/ui/swift-ui';
import { ignoreSafeArea } from '@expo/ui/swift-ui/modifiers';

// The iOS sheet header may place its close control in the Duo's system rail;
// its body reapplies the app's safe-area insets separately.
const horizontal = ignoreSafeArea({ regions: 'container', edges: 'horizontal' });
export function SheetContainer({ modifiers = [], ...props }) {
  return <BottomSheet {...props} modifiers={[horizontal, ...modifiers]} />;
}
export function SheetHost(props) {
  return <RNHostView {...props} modifiers={[horizontal]} />;
}
