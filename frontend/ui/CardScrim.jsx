import React from 'react';
import { View } from 'react-native';

const BAND_COUNT = 16;

export function CardScrim({ style }) {
  return <View pointerEvents="none" style={style}>
    {Array.from({ length: BAND_COUNT }, (_, index) => {
      const opacity = 0.98 * ((index + 1) / BAND_COUNT) ** 2;
      return <View key={index} style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: `${(index / BAND_COUNT) * 100}%`,
        height: `${100 / BAND_COUNT + 0.5}%`,
        backgroundColor: `rgba(17, 24, 39, ${opacity})`,
      }} />;
    })}
  </View>;
}
