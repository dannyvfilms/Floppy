import React from 'react';
import { BottomSheet } from '@expo/ui';
import { Button, NavigationStack, RNHostView, Toggle, Toolbar, ToolbarItem } from '@expo/ui/swift-ui';
import { ignoreSafeArea, toggleStyle } from '@expo/ui/swift-ui/modifiers';
import { useVerticalBarEdgeIOS } from 'expo-status-bar';
import { useDevicePose } from '../data/useDevicePose';

// The iOS sheet header may place its close control in the Duo's system rail;
// its body reapplies the app's safe-area insets separately.
const horizontal = ignoreSafeArea({ regions: 'container', edges: 'horizontal' });
const bottom = ignoreSafeArea({ regions: 'container', edges: 'bottom' });
export function SheetContainer({ modifiers = [], ...props }) {
  return <BottomSheet {...props} modifiers={[horizontal, ...modifiers]} />;
}
export function useNativeSheetClose(insets) {
  const pose = useDevicePose();
  const railEdge = useVerticalBarEdgeIOS();
  // Expo Go may not expose the vertical-bar trait; the hinge and sheet insets
  // identify its rail while leaving the inner portrait display horizontal.
  return railEdge || (pose.hasHinge && (insets.right > 0 ? 'right' : insets.left > 0 ? 'left' : null));
}
// railItems ({ value, label, icon }) become one group of rail buttons beside the close button,
// the way Calendar groups Filters and Settings. When the rail is too short (a half-height sheet)
// the system folds the last ones into its own "..." menu in the same group.
export function SheetHost({ nativeClose, onClose, railItems, railValue, onRailChange, children, ...props }) {
  const rail = Boolean(nativeClose && onClose && railItems?.length);
  if (!nativeClose || !onClose) return <RNHostView {...props} modifiers={[horizontal]}>{children}</RNHostView>;
  // Inside the NavigationStack the body would also stop above the bottom safe area, leaving a
  // blank band before the sheet's edge; let it run to the edge like the plain sheet does.
  const content = <RNHostView {...props} modifiers={[horizontal, bottom]}>{children}</RNHostView>;
  // @expo/ui's Toolbar wraps the body in one more layer per toolbar item, so a change in the
  // number of items rebuilds the body's RNHostView around the same React Native view. The old and
  // new hosts then share that view: the new one skips the touch handler the old one still holds,
  // the old one removes it (or the view itself) on disappearing, and the body stops responding or
  // shows blank. Keying the stack on the item count mounts a fresh body with its own views instead.
  // Callers also keep the list fixed while a sheet is open (TrackPresentation's trackRailItems).
  const itemCount = rail ? railItems.length : 0;
  // The system owns the rail's dynamically changing status-bar exclusion zone.
  return <NavigationStack key={`rail-${itemCount}`} modifiers={[bottom]}><Toolbar modifiers={[bottom]}>
    {content}
    <Toolbar.Content>
      <ToolbarItem placement="cancellationAction">
        <Button label="Close" systemImage="xmark" onPress={onClose} />
      </ToolbarItem>
      {/* Trailing items stack from the rail's far end, so the list goes in reversed to read
          top to bottom. A button-style toggle shows the open section inside the shared group. */}
      {[...(rail ? railItems : [])].reverse().map(item => <ToolbarItem key={item.value} placement="primaryAction">
        <Toggle label={item.label} systemImage={item.icon} isOn={item.value === railValue}
          onIsOnChange={() => onRailChange?.(item.value)} modifiers={[toggleStyle('button')]} />
      </ToolbarItem>)}
    </Toolbar.Content>
  </Toolbar></NavigationStack>;
}
