import React from 'react';
import { View } from 'react-native';
import { DateTimePicker } from './DateTimePicker';

// The Tracking date rows' time panel where there are no native wheels (web, Android): the shared
// DateTimePicker's time steppers. iOS supplies system wheels in expo/app/surfaces/TrackDatePanels.ios.jsx.
export function TrackTimeSteppers({ date, onValue, trackTime, palette }) {
  const pad = number => String(number).padStart(2, '0');
  const value = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + (trackTime ? `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` : '');
  return <View><DateTimePicker inline open value={value} onChange={onValue} trackTime={trackTime}
    palette={palette?.dateTime || {}} /></View>;
}

export const renderTimeSteppers = args => <TrackTimeSteppers {...args} />;
