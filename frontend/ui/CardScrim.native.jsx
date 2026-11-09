import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

export function CardScrim({ style }) {
  return <View pointerEvents="none" style={style}>
    <Svg style={StyleSheet.absoluteFill} preserveAspectRatio="none">
    <Defs>
      <LinearGradient id="media-card-scrim" x1="0%" y1="0%" x2="0%" y2="100%">
        <Stop offset="0%" stopColor="#111827" stopOpacity="0" />
        <Stop offset="40%" stopColor="#111827" stopOpacity="0.5" />
        <Stop offset="70%" stopColor="#111827" stopOpacity="0.85" />
        <Stop offset="100%" stopColor="#111827" stopOpacity="0.98" />
      </LinearGradient>
    </Defs>
    <Rect width="100%" height="100%" fill="url(#media-card-scrim)" />
    </Svg>
  </View>;
}
