import React from 'react';
import { Screen, Section } from '../components/Screen';
import CalendarSlot from '../surfaces/CalendarSlot';
import DateTimeSlot from '../surfaces/DateTimeSlot';

export default function CalendarScreen() {
  return <Screen title="Calendar" subtitle="Upcoming releases and what lands next">
    <Section title="This month">
      <CalendarSlot />
    </Section>
    <Section title="Tracking dates">
      <DateTimeSlot />
    </Section>
  </Screen>;
}
