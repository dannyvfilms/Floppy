import React from 'react';
import { DateTimePicker } from '../../../frontend/ui/DateTimePicker';

// Android and web have no native wheels for the Tracking date rows, so the time panel is the shared
// DateTimePicker's time steppers. iOS supplies the system controls in
// TrackDatePanels.ios.jsx. This file keeps the .jsx extension so Metro does not resolve it ahead of
// the .ios.jsx variant.
function sharedPicker({ date, onValue, trackTime, palette }) {
  const pad = number => String(number).padStart(2, '0');
  const value = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + (trackTime ? `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` : '');
  return <DateTimePicker inline open value={value} onChange={onValue} trackTime={trackTime}
    palette={palette?.dateTime || {}} />;
}

export const renderTimeWheels = sharedPicker;
// No month and year wheels here: the calendar's arrows step by month.
export const renderMonthYearWheels = undefined;
