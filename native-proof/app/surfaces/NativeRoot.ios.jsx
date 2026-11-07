import React from 'react';
import { View } from 'react-native';

export default function NativeRoot({ children, style }) {
  return <View style={style}>{children}</View>;
}
