import React from 'react';
import { View } from 'react-native';

export function CardScrim({ style }) {
  return <View pointerEvents="none" style={[style, {
    backgroundImage: 'linear-gradient(to bottom, rgba(17, 24, 39, 0), rgba(17, 24, 39, 0.5) 40%, rgba(17, 24, 39, 0.85) 70%, rgba(17, 24, 39, 0.98))',
  }]} />;
}
