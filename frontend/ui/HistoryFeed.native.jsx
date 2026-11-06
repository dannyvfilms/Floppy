import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { HistoryFeed as SharedHistoryFeed } from './HistoryFeed';

// Native counterpart for the browser history feed; the shared feed owns the
// day groups, rows and states.
export function HistoryFeed(props) {
  return <SharedHistoryFeed {...props} />;
}
