import React from 'react';
import { View } from 'react-native';

// Native implementation of the sidebar reveal contract. The browser variant
// animates height; native mounts the open block until its animation pass.
export function Reveal({ open, children }) {
  return open ? <View>{children}</View> : null;
}
