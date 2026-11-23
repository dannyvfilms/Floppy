import React from 'react';
import { Host, HStack, Picker, Text } from '@expo/ui/swift-ui';
import { frame, pickerStyle, tag } from '@expo/ui/swift-ui/modifiers';

// The system wheels for the Tracking date rows, as in iOS Calendar: hour, minute, second and AM or PM for the
// time (the seconds wheel is ours), and month and year behind the calendar's month button. Each host is
// given its final size up front; a matchContents host measures after it first draws and the panel jumped.
const range = (count, start = 0) => Array.from({ length: count }, (_, index) => start + index);
const pad = value => String(value).padStart(2, '0');

function Wheel({ value, onChange, items, width }) {
  return <Picker selection={String(value)} onSelectionChange={next => onChange(next)}
    modifiers={[pickerStyle('wheel'), frame({ width, height: 170 })]}>
    {items.map(item => <Text key={item.value} modifiers={[tag(String(item.value))]}>{item.label}</Text>)}
  </Picker>;
}

export function renderTimeWheels({ date, onChange }) {
  const pm = date.getHours() >= 12;
  const hour = date.getHours() % 12 || 12;
  const set = (nextHour, minute, second, nextPm) => {
    const next = new Date(date);
    next.setHours((nextHour % 12) + (nextPm ? 12 : 0), minute, second, 0);
    onChange(next);
  };
  return <Host style={{ width: 320, height: 170 }}>
    <HStack spacing={0}>
      <Wheel width={80} value={hour} items={range(12, 1).map(value => ({ value, label: String(value) }))}
        onChange={next => set(Number(next), date.getMinutes(), date.getSeconds(), pm)} />
      <Wheel width={80} value={date.getMinutes()} items={range(60).map(value => ({ value, label: pad(value) }))}
        onChange={next => set(hour, Number(next), date.getSeconds(), pm)} />
      <Wheel width={80} value={date.getSeconds()} items={range(60).map(value => ({ value, label: pad(value) }))}
        onChange={next => set(hour, date.getMinutes(), Number(next), pm)} />
      <Wheel width={80} value={pm ? 'PM' : 'AM'} items={[{ value: 'AM', label: 'AM' }, { value: 'PM', label: 'PM' }]}
        onChange={next => set(hour, date.getMinutes(), date.getSeconds(), next === 'PM')} />
    </HStack>
  </Host>;
}

const MONTHS = Array.from({ length: 12 }, (_, month) => new Intl.DateTimeFormat(undefined, { month: 'long' }).format(new Date(2024, month, 1)));

export function renderMonthYearWheels({ year, month, onChange }) {
  const years = range(201, 1950).map(value => ({ value, label: String(value) }));
  return <Host style={{ width: 309, height: 170 }}>
    <HStack spacing={0}>
      <Wheel width={170} value={month} items={MONTHS.map((label, value) => ({ value, label }))}
        onChange={next => onChange(year, Number(next))} />
      <Wheel width={120} value={year} items={years} onChange={next => onChange(Number(next), month)} />
    </HStack>
  </Host>;
}
