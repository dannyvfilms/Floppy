import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { monthWeeks, weekdayLabels } from './dateTime';

// The month calendar of the Tracking date rows, drawn at the size iOS Calendar uses (309 pt wide, 44 pt
// rows and columns) so it never stretches or jumps the way the system picker does inside a sheet.
// Pressing the month opens month and year wheels, which a platform supplies (`renderMonthYear`); without
// them the month button is not shown and the arrows step by month.
const WIDTH = 309;
const CELL = 44;

function sameDay(date, cell) {
  return date.getFullYear() === cell.year && date.getMonth() === cell.month && date.getDate() === cell.day;
}

export function TrackCalendar({ date, onSelect, palette, renderMonthYear, locale }) {
  // Today's number and the arrows use the brighter accent when the host supplies one (dark cards).
  const accent = palette.accentBright || palette.accent;
  const [view, setView] = useState({ year: date.getFullYear(), month: date.getMonth() });
  const [wheels, setWheels] = useState(false);
  useEffect(() => {
    setView({ year: date.getFullYear(), month: date.getMonth() });
  }, [date.getFullYear(), date.getMonth()]);
  const today = new Date();
  const weeks = monthWeeks(view.year, view.month, 'sunday').filter(week => week.some(cell => cell.inMonth));
  const weekdays = weekdayLabels('sunday', locale);
  const title = (() => {
    try {
      return new Intl.DateTimeFormat(locale || undefined, { month: 'long', year: 'numeric' })
        .format(new Date(view.year, view.month, 1));
    } catch {
      return `${view.year}-${view.month + 1}`;
    }
  })();
  const step = amount => {
    const next = new Date(view.year, view.month + amount, 1);
    setView({ year: next.getFullYear(), month: next.getMonth() });
  };
  const tint = /^#[0-9a-f]{6}$/i.test(palette.accent || '') ? `${palette.accent}26` : 'transparent';
  const arrow = (amount, spec, label) => <Pressable accessibilityRole="button" accessibilityLabel={label}
    hitSlop={8} onPress={() => step(amount)} style={styles.arrow}>
    <Icon spec={spec} color={accent} size={22} />
  </Pressable>;
  return <View style={styles.root}>
    <View style={styles.header}>
      {renderMonthYear
        ? <Pressable accessibilityRole="button" accessibilityLabel={title} accessibilityState={{ expanded: wheels }}
          onPress={() => setWheels(current => !current)} style={styles.title}>
          <Text style={[styles.titleText, { color: palette.text }]}>{title}</Text>
          <View style={wheels ? styles.open : undefined}><Icon spec={actionIcons.chevronRight} color={accent} size={16} /></View>
        </Pressable>
        : <Text style={[styles.titleText, { color: palette.text }]}>{title}</Text>}
      <View style={styles.arrows}>
        {arrow(-1, actionIcons.chevronLeft, 'Previous month')}
        {arrow(1, actionIcons.chevronRight, 'Next month')}
      </View>
    </View>
    {wheels && renderMonthYear ? <View style={styles.wheels}>
      {renderMonthYear({ year: view.year, month: view.month, onChange: (year, month) => setView({ year, month }) })}
    </View> : <>
      <View style={styles.weekdays}>
        {weekdays.map(label => <Text key={label} style={[styles.weekday, { color: palette.textMuted }]}>{label.toUpperCase()}</Text>)}
      </View>
      <View style={styles.grid}>
        {weeks.map((week, index) => <View key={index} style={styles.week}>
          {week.map(cell => {
            if (!cell.inMonth) return <View key={`${cell.month}-${cell.day}`} style={styles.cell} />;
            const selected = sameDay(date, cell);
            const current = sameDay(today, cell);
            return <Pressable key={cell.day} accessibilityRole="button" accessibilityState={{ selected }}
              accessibilityLabel={`${title} ${cell.day}`} style={styles.cell}
              onPress={() => onSelect(new Date(cell.year, cell.month, cell.day, date.getHours(), date.getMinutes(), date.getSeconds()))}>
              <View style={[styles.day, selected && { backgroundColor: palette.text }, !selected && current && { backgroundColor: tint }]}>
                <Text style={[styles.dayText, { color: selected ? palette.surface : current ? accent : palette.text },
                  selected && styles.selected]}>{cell.day}</Text>
              </View>
            </Pressable>;
          })}
        </View>)}
      </View>
    </>}
  </View>;
}

const styles = StyleSheet.create({
  root: { width: WIDTH, alignSelf: 'center' },
  header: { height: 42, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 10, paddingRight: 8 },
  title: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  titleText: { fontSize: 17, fontWeight: '600' },
  open: { transform: [{ rotate: '90deg' }] },
  arrows: { flexDirection: 'row', alignItems: 'center', gap: 20 },
  arrow: { width: 24, alignItems: 'center' },
  weekdays: { marginTop: 7, height: 29, flexDirection: 'row', alignItems: 'center' },
  weekday: { width: WIDTH / 7, textAlign: 'center', fontSize: 13, fontWeight: '600' },
  // Spacing measured from the iOS Calendar reference: weekday labels 30 pt above the first week.
  grid: { marginTop: -6 },
  week: { flexDirection: 'row', height: CELL },
  cell: { width: WIDTH / 7, height: CELL, alignItems: 'center', justifyContent: 'center' },
  day: { width: 43, height: 43, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  dayText: { fontSize: 20 },
  selected: { fontWeight: '700' },
  wheels: { alignItems: 'center', marginTop: 8 },
});
