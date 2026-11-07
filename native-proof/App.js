import NativeStatusBar from './app/components/NativeStatusBar';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, SafeAreaView, ScrollView, StyleSheet, View } from 'react-native';
import { getActiveAuthSession, subscribeAuthSession } from './app/data/authSession';
import { restoreAuthSession } from './app/data/authTransport';
import { EXTRA_SCREENS } from './app/extraScreens';
import { installNativeIconRenderer } from './app/iconRenderer';
import floppyLogo from './assets/floppy-logo.png';
import AuthScreen from './app/screens/AuthScreen';
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
import ShellSlot from './app/surfaces/ShellSlot';
import NativeRoot from './app/surfaces/NativeRoot';
import { statusBarInset } from './app/status-bar-inset';
import { palette } from './app/theme';

installNativeIconRenderer();

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
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [restoring, setRestoring] = useState(true);
  const [tab, setTab] = useState('home');
  const [libraryType, setLibraryType] = useState('movie');
  const [stack, setStack] = useState([]);
  const navigate = (screen, params) => setStack(current => [...current, { screen, params }]);
  const openTab = next => { setStack([]); setTab(next); };
  const back = () => setStack(current => current.slice(0, -1));
  const active = stack[stack.length - 1];

  // Web requires a session before it renders any app page; native does the
  // same instead of showing a demo library that looks like real data.
  useEffect(() => {
    const unsubscribe = subscribeAuthSession(setSession);
    restoreAuthSession().catch(() => {}).finally(() => setRestoring(false));
    return unsubscribe;
  }, []);

  if (restoring) {
    return <SafeAreaView style={[styles.root, { paddingTop: statusBarInset, alignItems: 'center', justifyContent: 'center' }]}>
      <NativeStatusBar backgroundColor={palette.background} />
      <ActivityIndicator color={palette.accentStrong} />
    </SafeAreaView>;
  }
  if (!session) {
    return <SafeAreaView style={[styles.root, { paddingTop: statusBarInset }]}>
      <NativeStatusBar backgroundColor={palette.background} />
      <ScrollView contentContainerStyle={styles.entrance} keyboardShouldPersistTaps="handled">
        <Image source={floppyLogo} accessibilityLabel="Floppy"
          resizeMode="contain" style={styles.entranceLogo} />
        <AuthScreen navigate={() => {}} entranceOnly />
      </ScrollView>
    </SafeAreaView>;
  }

  // The drawer speaks in web hrefs, the same values the server navigation
  // model carries. Map them onto the native surfaces here, once.
  const openHref = href => {
    const path = String(href || '');
    if (path === '/') { openTab('home'); return; }
    if (path === '/discover') { openTab('discover'); return; }
    if (path === '/calendar') { openTab('calendar'); return; }
    if (path.startsWith('/settings') || path === '/appearance') { openTab('settings'); return; }
    const media = path.match(/^\/medialist\/([^/?#]+)/);
    if (media) { setLibraryType(media[1]); openTab('library'); return; }
    if (path.startsWith('/collection')) { navigate('Collection'); return; }
    if (path.startsWith('/history')) { navigate('History'); return; }
    if (path.startsWith('/lists')) { navigate('Lists'); return; }
    if (path.startsWith('/statistics')) { navigate('Statistics'); return; }
    if (path.startsWith('/tags')) { navigate('Tags'); return; }
    if (path.startsWith('/details/')) { navigate('Detail', { href: path }); }
  };

  const activeHref = active
    ? ''
    : tab === 'home' ? '/'
      : tab === 'discover' ? '/discover'
        : tab === 'calendar' ? '/calendar'
          : tab === 'settings' ? '/settings/account'
            : tab === 'library' ? `/medialist/${libraryType}` : '';
  const ActiveScreen = active ? STACK_SCREENS[active.screen] : TAB_SCREENS[tab];
  const tabParams = tab === 'library' ? { mediaType: libraryType } : undefined;

  return <NativeRoot style={[styles.root, { paddingTop: statusBarInset }]}>
    <NativeStatusBar backgroundColor={palette.background} />
    <ShellSlot active={tab} activeHref={activeHref} onNavigate={openTab} onOpenHref={openHref}
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}>
      <View style={styles.body}>
        {active
          ? <ActiveScreen params={active.params} navigate={navigate} onBack={back} />
          : <ActiveScreen navigate={navigate} params={tabParams} />}
      </View>
    </ShellSlot>
  </NativeRoot>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.background },
  body: { flex: 1, minHeight: 0 },
  entrance: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 16, paddingVertical: 24 },
  entranceLogo: { width: 211, height: 64, alignSelf: 'center' },
});
