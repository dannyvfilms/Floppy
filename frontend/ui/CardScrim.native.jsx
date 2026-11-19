import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

export function CardScrim({ style }) {
  return <View pointerEvents="none" style={style}>
    {/* A 1x1 viewBox stretched to the view: the gradient follows the card when it is resized
        (rotating or opening a foldable). Without a viewBox the canvas kept its first width and
        the scrim stopped partway across a card that grew wider. */}
    <Svg width="100%" height="100%" viewBox="0 0 1 1" preserveAspectRatio="none" style={StyleSheet.absoluteFill}>
    <Defs>
      <LinearGradient id="media-card-scrim" x1="0%" y1="0%" x2="0%" y2="100%">
        <Stop offset="0%" stopColor="#111827" stopOpacity="0" />
        <Stop offset="40%" stopColor="#111827" stopOpacity="0.5" />
        <Stop offset="70%" stopColor="#111827" stopOpacity="0.85" />
        <Stop offset="100%" stopColor="#111827" stopOpacity="0.98" />
      </LinearGradient>
    </Defs>
    <Rect x="0" y="0" width="1" height="1" fill="url(#media-card-scrim)" />
    </Svg>
  </View>;
}
