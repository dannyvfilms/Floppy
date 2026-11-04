import React from 'react';
import { Screen, Section } from '../components/Screen';
import CalendarSlot from '../surfaces/CalendarSlot';
import DateTimeSlot from '../surfaces/DateTimeSlot';

export default function CalendarScreen({ navigate }) {
  return <Screen title="Calendar" subtitle="Upcoming releases and what lands next">
    <Section title="This month">
      <CalendarSlot onOpenRelease={() => navigate('Detail')} />
    </Section>
    <Section title="Tracking dates">
      <DateTimeSlot />
    </Section>
  </Screen>;
}
