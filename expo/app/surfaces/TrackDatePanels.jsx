import React from 'react';
import { TrackTimeSteppers } from '../../../frontend/ui/trackDatePanels';

// Android and web have no native wheels for the Tracking date rows, so the time panel is the shared
// DateTimePicker's time steppers (frontend/ui/trackDatePanels.jsx). iOS supplies the system controls in
// TrackDatePanels.ios.jsx. This file keeps the .jsx extension so Metro does not resolve it ahead of
// the .ios.jsx variant.
export const renderTimeWheels = args => <TrackTimeSteppers {...args} />;
// No month and year wheels here: the calendar's arrows step by month.
export const renderMonthYearWheels = undefined;
