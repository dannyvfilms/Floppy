import React from 'react';
import { Pressable, Text } from 'react-native';
import { GlassView } from 'expo-glass-effect';

export function SheetCloseButton({ onPress, color }) {
  return <GlassView isInteractive glassEffectStyle="regular" style={{ borderRadius: 22, overflow: 'hidden' }}>
    <Pressable accessibilityRole="button" accessibilityLabel="Close sheet" onPress={onPress}
      style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
      <Text style={{ color, fontSize: 28, lineHeight: 32 }}>×</Text>
    </Pressable>
  </GlassView>;
}
