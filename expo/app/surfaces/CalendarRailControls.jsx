import React from 'react';
import { View } from 'react-native';

// Android and web do not expose the iOS system side rail.
export function useCalendarRail() { return false; }
export default function CalendarRailControls() { return <View />; }
