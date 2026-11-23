import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CollectionRow, separatorStyle } from './CollectionCopies';
import { systemFillColor } from './separatorColor';
import { TrackCalendar } from './TrackCalendar';
import { formatDisplayText, pad2, parseDateValue, valueFromDate } from './dateTime';

// A date row modelled on iOS Calendar's: at rest two buttons show the chosen date and, when the form
// tracks time, the time. Pressing the date opens a calendar beneath the row, pressing the time opens
// hour, minute and second wheels.
// The calendar is TrackCalendar; the time wheels and the calendar's month and year wheels are native
// controls a platform supplies (`renderTime`, `renderMonthYear`).
// Native only: web keeps the compact DateTimePicker field in TrackForm.

function timeText(parts) {
  const hour = parts.hour % 12 || 12;
  // Hours and minutes only, as iOS Calendar shows; the seconds are on the wheels.
  return { clock: `${hour}:${pad2(parts.minute)}`, meridiem: parts.hour >= 12 ? 'PM' : 'AM' };
}

function partsToDate(parts) {
  return new Date(parts.year, parts.month, parts.day, parts.hour, parts.minute, parts.second);
}

export function TrackDateRow({
  label, icon, value, trackTime, error, palette, labels = {}, onChange,
  renderMonthYear, renderTime, mode, onModeChange,
}) {
  const parts = parseDateValue(value);
  const date = parts ? partsToDate(parts) : new Date();
  const emit = next => onChange(valueFromDate(next, trackTime), { source: 'picker' });
  // One picker is open at a time; the form owns which, so opening another row closes this one.
  const toggle = which => onModeChange(mode === which ? null : which);
  // The time button sets AM or PM smaller than the clock, as iOS Calendar does.
  const pill = (which, text, muted) => <Pressable accessibilityRole="button"
    accessibilityLabel={`${label}: ${typeof text === 'string' ? text : `${text.clock} ${text.meridiem}`}`}
    accessibilityState={{ expanded: mode === which }} onPress={() => toggle(which)}
    style={({ pressed }) => [styles.pill, { backgroundColor: systemFillColor() || palette.surfaceStrong, opacity: pressed ? 0.72 : 1 }]}>
    <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={[styles.pillText, { color: muted ? palette.textMuted : palette.text }]}>{typeof text === 'string' ? text
      : <>{text.clock}<Text style={styles.meridiem}> {text.meridiem}</Text></>}</Text>
  </Pressable>;
  const args = { date, onChange: emit, onValue: onChange, trackTime, palette };
  let panel = null;
  if (mode === 'date') panel = <TrackCalendar date={date} onSelect={emit} palette={palette} renderMonthYear={renderMonthYear} />;
  else if (mode === 'time') panel = renderTime?.(args) ?? null;
  // The group's hairline, indented past the icon like its other dividers, between the row and its panel.
  const divider = <View style={[separatorStyle(palette), { marginLeft: icon ? 28 : 0 }]} />;
  return <View>
    <CollectionRow icon={icon} label={label} palette={palette}>
      <View style={styles.pills}>
        {pill('date', parts ? formatDisplayText(parts, false, false) : (labels.notSet || 'Not set'), !parts)}
        {parts && trackTime ? pill('time', timeText(parts)) : null}
      </View>
    </CollectionRow>
    {mode ? <View style={styles.panel}>
      {divider}
      {panel ? <View style={styles.centered}>{panel}</View> : null}
      {parts ? <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${labels.clear || 'Clear'}`}
        onPress={() => { onChange('', { source: 'picker' }); onModeChange(null); }} style={styles.clear}>
        <Text style={[styles.clearText, { color: palette.danger }]}>{labels.clear || 'Clear'}</Text>
      </Pressable> : null}
    </View> : null}
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  pills: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1, minWidth: 0 },
  pill: { borderRadius: 17, paddingHorizontal: 12, paddingVertical: 6, flexShrink: 1, minWidth: 0 },
  pillText: { fontSize: 17 },
  meridiem: { fontSize: 14 },
  panel: { paddingBottom: 4 },
  // Spacing measured from iOS Calendar: 44pt from the divider to the month header, 41pt from the last week to the next divider.
  centered: { alignItems: 'center', paddingTop: 20, paddingBottom: 24 },
  clear: { alignSelf: 'center', paddingHorizontal: 16, paddingVertical: 8 },
  clearText: { fontSize: 17 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
});
