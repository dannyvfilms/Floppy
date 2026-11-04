import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { DateTimePicker } from '../../../frontend/ui/DateTimePicker';
import { valueFromDate } from '../../../frontend/ui/dateTime';
import { dateTimePalette, spacing } from '../theme';

export const surface = {
  id: 'DATE-TIME',
  status: 'ported',
  title: 'Tracking date and time picker',
  where: 'Tracking dialogs and History date ranges',
  note: 'The shared React Native field keeps quick actions, optional time, locale-aware calendar navigation, marked days and the hidden value contract. The dynamic-expression bulk episode form stays on the Alpine fallback.',
};

const labels = {
  field: 'Watch date',
  mobileLabel: 'Watch date',
  notSet: 'Not set',
  openPicker: 'Open watch date picker',
  picker: 'Watch date picker',
  quickActions: 'Watch date quick actions',
  clear: 'Clear date',
  close: 'Close date picker',
  previousMonth: 'Previous month',
  nextMonth: 'Next month',
  selectMonth: 'Select month',
  previousYear: 'Previous year',
  nextYear: 'Next year',
  selectYear: 'Select year',
  previousYears: 'Previous years',
  nextYears: 'Next years',
  year: 'Year',
  back: 'Back',
  time: 'Time',
  now: 'Now',
  none: 'None',
  suggestedDate: 'Suggested date',
  hour: 'Hour',
  minute: 'Minute',
  second: 'Second',
  earlierHour: 'Earlier hour',
  laterHour: 'Later hour',
  earlierMinute: 'Earlier minute',
  laterMinute: 'Later minute',
  earlierSecond: 'Earlier second',
  laterSecond: 'Later second',
  activity: 'View activity for',
};

const quickActions = [
  { id: 'start-now', label: 'Start Now' },
  { id: 'just-finished', label: 'Just Finished' },
  { id: 'release-date', label: 'Release Date', requiresSuggestion: true },
];

const markerDays = [
  '2026-11-01',
  '2026-11-03',
  '2026-11-04',
  '2026-11-08',
  '2026-11-12',
  '2026-11-18',
  '2026-11-25',
];

export default function DateTimeSlot() {
  const [value, setValue] = useState('2026-11-03T20:30');

  function applyQuickAction(action) {
    if (action === 'release-date') {
      setValue('2026-11-14T20:00');
      return;
    }
    setValue(valueFromDate(new Date(), true));
  }

  return <View style={styles.wrapper}>
    <DateTimePicker
      value={value}
      onChange={next => setValue(next)}
      trackTime
      use12Hour={false}
      weekStart="monday"
      locale="en-US"
      labels={labels}
      quickActions={quickActions}
      suggestionDate="2026-11-14"
      suggestionLabel="Release Date"
      suggestionExtras={[
        { date: '2026-11-07', label: 'First episode' },
        { date: '2026-11-21', label: 'Finale' },
      ]}
      copyValue="2026-11-03T21:45"
      copyLabel="Copy from End"
      markerDays={markerDays}
      onQuickAction={applyQuickAction}
      palette={dateTimePalette} />
  </View>;
}

const styles = StyleSheet.create({
  wrapper: { marginTop: spacing.xs },
});
