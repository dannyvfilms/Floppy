import React, { useRef } from 'react';
import { Vibration } from 'react-native';
import { MenuView } from '@expo/ui/community/menu';

// The Android card Pressable consumes the hold; show the Material menu from it
// and provide feedback because the native wrapper does not trigger a haptic.
// A divider entry becomes an inline section: Material draws the lines around it.
function withSections(actions) {
  const at = actions.findIndex(action => action.divider);
  if (at < 0) return actions;
  return [...actions.slice(0, at), { id: 'section', title: '', displayInline: true, subactions: actions.slice(at + 1) }];
}

export default function NativeCardMenu({ actions, onPressAction, children }) {
  const menu = useRef(null);
  return <MenuView ref={menu} actions={withSections(actions)} shouldOpenOnLongPress
    onOpenMenu={() => Vibration.vibrate(10)} onPressAction={onPressAction}>
    {React.cloneElement(children, { onLongPress: () => menu.current?.show() })}
  </MenuView>;
}
