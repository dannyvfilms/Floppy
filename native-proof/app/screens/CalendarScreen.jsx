import React from 'react';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';

const calendar = {
  id: 'RELEASE-CALENDAR',
  title: 'Release calendar',
  where: 'Calendar month, agenda and list views',
  note: 'The month grid, agenda, release filters and subscription controls will appear here. The gear menu is already React-owned on the web.',
};
const dateTime = {
  id: 'DATE-TIME',
  title: 'Tracking date and time',
  where: 'Tracking dialogs and History date ranges',
  note: 'The native date/time picker will replace this note when tracking forms are ported.',
};

export default function CalendarScreen() {
  return <Screen title="Calendar" subtitle="Upcoming releases and what lands next">
    <Section title="This month">
      <Note surface={calendar} />
    </Section>
    <Section title="Tracking dates">
      <Note surface={dateTime} />
    </Section>
  </Screen>;
}
