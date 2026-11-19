import React from 'react';
import { SafeAreaView } from 'react-native';

export default function NativeRoot({ children, style }) {
  return <SafeAreaView style={style}>{children}</SafeAreaView>;
}
