import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { ProgressCard as SharedProgressCard } from './ProgressCard.jsx';

export function ProgressCard(props) {
  return <SharedProgressCard {...props} />;
}
