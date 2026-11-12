import React from 'react';
import { StatusBar } from 'react-native';

export default function NativeStatusBar({ backgroundColor }) {
  return <StatusBar barStyle="light-content" backgroundColor={backgroundColor} />;
}
