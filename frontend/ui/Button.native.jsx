import React from 'react';
import { View } from 'react-native';
import { Button as SharedButton } from './Button.jsx';

export function Button(props) {
  return <View><SharedButton {...props} /></View>;
}
