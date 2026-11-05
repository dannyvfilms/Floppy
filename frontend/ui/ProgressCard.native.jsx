import React from 'react';
import { View } from 'react-native';
import { ProgressCard as SharedProgressCard } from './ProgressCard.jsx';

export function ProgressCard(props) {
  return <View><SharedProgressCard {...props} /></View>;
}
