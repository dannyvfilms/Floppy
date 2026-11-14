import React from 'react';
import { Pressable, Text } from 'react-native';
import { GlassView } from 'expo-glass-effect';

export function SheetCloseButton({ onPress, color }) {
  // The Duo's native rail controls are 48 points; other platforms keep their own control sizing.
  return <GlassView isInteractive glassEffectStyle="regular" style={{ borderRadius: 24, overflow: 'hidden' }}>
    <Pressable accessibilityRole="button" accessibilityLabel="Close sheet" onPress={onPress}
      style={{ width: 48, height: 48, alignItems: 'center', justifyContent: 'center' }}>
      <Text style={{ color, fontSize: 28, lineHeight: 32 }}>×</Text>
    </Pressable>
  </GlassView>;
}
