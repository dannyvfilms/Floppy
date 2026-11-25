import React from 'react';
import { BottomSheet, RNHostView } from '@expo/ui';

export function SheetContainer(props) { return <BottomSheet {...props} />; }
export function useNativeSheetClose() { return false; }
// Only iOS has the system rail; its rail items have nowhere to go here.
export function SheetHost({ nativeClose, onClose, railItems, railValue, onRailChange, ...props }) {
  return <RNHostView {...props} />;
}
