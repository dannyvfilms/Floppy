import React, { useMemo } from 'react';
import { View } from 'react-native';
import { SafeAreaInsetsContext, SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';

function ScreenInsets({ children, outer }) {
  const inner = useSafeAreaInsets();
  // The navigator owns vertical safe areas; the screen measures its own Split View edges.
  const insets = useMemo(() => ({ ...outer, left: inner.left, right: inner.right }),
    [outer, inner.left, inner.right]);
  return <SafeAreaInsetsContext.Provider value={insets}>{children}</SafeAreaInsetsContext.Provider>;
}

export default function NativeRoot({ children, style }) {
  const outer = useSafeAreaInsets();
  return <View style={style}><SafeAreaProvider><ScreenInsets outer={outer}>{children}</ScreenInsets></SafeAreaProvider></View>;
}
