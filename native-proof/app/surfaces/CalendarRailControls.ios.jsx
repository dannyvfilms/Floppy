import React from 'react';
import { Stack } from 'expo-router';
import { useImage } from 'expo-image';
import { useColorScheme } from 'react-native';
import { useVerticalBarEdgeIOS } from 'expo-status-bar';
import { useDevicePose } from '../data/useDevicePose';
import { palette } from '../theme';

// The system side rail exists on a hinged device or when iOS moves the status bar vertically.
export function useCalendarRail() {
  const pose = useDevicePose();
  const railEdge = useVerticalBarEdgeIOS();
  return Boolean(pose.hasHinge || railEdge);
}

export default function CalendarRailControls({ mediaTypes, statusOptions, selectedTypes,
  selectedStatusesByType, toggleType, toggleStatus, clearFilters,
  labels, menuLabels, weekStart, menuAction, today }) {
  const foreground = useColorScheme() === 'dark' ? 'white' : 'black';
  const weekday = today ? new Date(today.year, today.month - 1, today.day)
    .toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase() : '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44" viewBox="0 0 44 44">
    <text x="22" y="16" text-anchor="middle" font-family="-apple-system" font-size="10" font-weight="700" fill="${foreground}">${weekday}</text>
    <text x="22" y="35" text-anchor="middle" font-family="-apple-system" font-size="20" fill="${foreground}">${today?.day || ''}</text>
  </svg>`;
  const dateImage = useImage(`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`, {}, [svg]);
  return <Stack.Toolbar placement="bottom">
    <Stack.Toolbar.Spacer />
    {today && dateImage ? <Stack.Toolbar.Button image={dateImage} imageRenderingMode="original" separateBackground
      accessibilityLabel={menuLabels.today} tintColor={palette.text} onPress={() => menuAction('today')} /> : null}
    {today && dateImage ? <Stack.Toolbar.Spacer width={8} sharesBackground={false} /> : null}
    <Stack.Toolbar.Menu icon="line.3.horizontal.decrease" accessibilityLabel={labels.filters} tintColor={palette.text}>
      <Stack.Toolbar.Menu title={labels.mediaTypes}>
        {mediaTypes.map(item => <Stack.Toolbar.MenuAction key={item.value} isOn={selectedTypes.includes(item.value)}
          onPress={() => toggleType(item.value)}>{item.label}</Stack.Toolbar.MenuAction>)}
      </Stack.Toolbar.Menu>
      <Stack.Toolbar.Menu title={labels.status}>
        {statusOptions.map(status => <Stack.Toolbar.MenuAction key={status.value}
          isOn={Object.values(selectedStatusesByType).some(values => values.includes(status.value))}
          onPress={() => toggleStatus(status.value)}>{status.label}</Stack.Toolbar.MenuAction>)}
      </Stack.Toolbar.Menu>
      <Stack.Toolbar.MenuAction onPress={clearFilters}>{labels.clearAll}</Stack.Toolbar.MenuAction>
    </Stack.Toolbar.Menu>
    <Stack.Toolbar.Menu icon="gearshape" accessibilityLabel={menuLabels.menu} tintColor={palette.text}>
      <Stack.Toolbar.MenuAction icon="square.and.arrow.down" onPress={() => menuAction('download')}>{menuLabels.download}</Stack.Toolbar.MenuAction>
      <Stack.Toolbar.MenuAction icon="arrow.clockwise" onPress={() => menuAction('fetch')}>Refresh Calendar</Stack.Toolbar.MenuAction>
      <Stack.Toolbar.Menu title="Week Start" icon="calendar">
        {['monday', 'sunday'].map(value => <Stack.Toolbar.MenuAction key={value} isOn={weekStart === value}
          onPress={() => menuAction('weekStart', value)}>{menuLabels[value]}</Stack.Toolbar.MenuAction>)}
      </Stack.Toolbar.Menu>
    </Stack.Toolbar.Menu>

  </Stack.Toolbar>;
}
