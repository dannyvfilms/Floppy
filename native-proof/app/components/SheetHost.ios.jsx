import React from 'react';
import { BottomSheet } from '@expo/ui';
import { RNHostView } from '@expo/ui/swift-ui';
import { ignoreSafeArea } from '@expo/ui/swift-ui/modifiers';

// A presented sheet may use the Duo's horizontal system rail area.
const horizontal = ignoreSafeArea({ regions: 'container', edges: 'horizontal' });
export function SheetContainer({ modifiers = [], ...props }) {
  return <BottomSheet {...props} modifiers={[horizontal, ...modifiers]} />;
}
export function SheetHost(props) {
  return <RNHostView {...props} modifiers={[horizontal]} />;
}
