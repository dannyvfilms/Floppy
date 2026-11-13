import React from 'react';
import { Pressable, Text } from 'react-native';

// Native Liquid Glass is iOS-only; use a conventional surface on Android and web.
export function SheetCloseButton({ onPress, color }) {
  return <Pressable accessibilityRole="button" accessibilityLabel="Close sheet" onPress={onPress}
    style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: '#333', alignItems: 'center', justifyContent: 'center' }}>
    <Text style={{ color, fontSize: 28, lineHeight: 32 }}>×</Text>
  </Pressable>;
}
