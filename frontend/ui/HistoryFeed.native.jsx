import React from 'react';
import { View } from 'react-native';
import { HistoryFeed as SharedHistoryFeed } from './HistoryFeed';

// Native counterpart for the browser history feed; the shared feed owns the
// day groups, rows and states.
export function HistoryFeed(props) {
  return <View><SharedHistoryFeed {...props} /></View>;
}
