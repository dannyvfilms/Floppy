import React, { useState } from 'react';
import { SafeAreaView, StatusBar, StyleSheet, View } from 'react-native';
import { TabBar } from './app/components/TabBar';
import { EXTRA_SCREENS } from './app/extraScreens';
import CalendarScreen from './app/screens/CalendarScreen';
import DetailScreen from './app/screens/DetailScreen';
import DiscoverScreen from './app/screens/DiscoverScreen';
import HistoryScreen from './app/screens/HistoryScreen';
import HomeScreen from './app/screens/HomeScreen';
import LibraryScreen from './app/screens/LibraryScreen';
import ListDetailScreen from './app/screens/ListDetailScreen';
import ListsScreen from './app/screens/ListsScreen';
import SearchScreen from './app/screens/SearchScreen';
import SettingsScreen from './app/screens/SettingsScreen';
import StatisticsScreen from './app/screens/StatisticsScreen';
import { statusBarInset } from './app/status-bar-inset';
import { palette } from './app/theme';

const TAB_SCREENS = {
  home: HomeScreen,
  discover: DiscoverScreen,
  library: LibraryScreen,
  calendar: CalendarScreen,
  settings: SettingsScreen,
};

const STACK_SCREENS = {
  Detail: DetailScreen,
  ListDetail: ListDetailScreen,
  Lists: ListsScreen,
  History: HistoryScreen,
  Statistics: StatisticsScreen,
  Search: SearchScreen,
  ...EXTRA_SCREENS,
};

export default function App() {
  const [tab, setTab] = useState('home');
  const [stack, setStack] = useState([]);
  const navigate = (screen, params) => setStack(current => [...current, { screen, params }]);
  const back = () => setStack(current => current.slice(0, -1));
  const active = stack[stack.length - 1];
  const ActiveScreen = active ? STACK_SCREENS[active.screen] : TAB_SCREENS[tab];
  return <SafeAreaView style={[styles.root, { paddingTop: statusBarInset }]}>
    <StatusBar barStyle="light-content" backgroundColor={palette.background} />
    <View style={styles.body}>
      {active
        ? <ActiveScreen params={active.params} navigate={navigate} onBack={back} />
        : <ActiveScreen navigate={navigate} />}
    </View>
    {active ? null : <TabBar active={tab} onChange={setTab} />}
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.background },
  body: { flex: 1, minHeight: 0 },
});
