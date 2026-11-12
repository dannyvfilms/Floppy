import React from 'react';
import { Text } from 'react-native';

export function RatingStarIcon(lit, size = 20) {
  return <Text style={{ fontSize: size, lineHeight: size, color: lit ? '#facc15' : '#4b5563' }}>★</Text>;
}
