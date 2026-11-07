import React from 'react';
import { View } from 'react-native';

// The same stops as the web `.bg-card-body` gradient: transparent, 50% at
// 40%, 85% at 70%, 98% at the bottom. Bands keep one implementation for every
// renderer; at card width the steps are below the visible threshold.
const STOPS = [[0, 0], [0.4, 0.5], [0.7, 0.85], [1, 0.98]];
const BANDS = 16;

function opacityAt(t) {
  for (let index = 1; index < STOPS.length; index += 1) {
    const [end, endValue] = STOPS[index];
    const [start, startValue] = STOPS[index - 1];
    if (t <= end) {
      const span = end - start || 1;
      return startValue + ((t - start) / span) * (endValue - startValue);
    }
  }
  return STOPS[STOPS.length - 1][1];
}

const COLORS = Array.from({ length: BANDS }, (_, index) => (
  `rgba(17, 24, 39, ${opacityAt((index + 0.5) / BANDS).toFixed(3)})`
));

export function CardScrim({ style }) {
  return <View pointerEvents="none" style={style}>
    {COLORS.map((color, index) => <View key={index} style={{ flex: 1, backgroundColor: color }} />)}
  </View>;
}
