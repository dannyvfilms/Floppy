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
  Settings: SettingsScreen,
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
  const [tabHistory, setTabHistory] = useState([]);
  const navigate = (screen, params) => {
    // Music and podcast library rows are song and episode trackers whose
    // detail surfaces live on the Music screen, which reads the row payload
    // directly. Search results keep the generic detail page because they do
    // not carry the server row the music screen maps.
    const rowMediaType = params?.item?.media
      ? (params?.item?.identity?.mediaType || params?.item?.media?.item?.media_type || '')
      : '';
    if (screen === 'Detail' && (rowMediaType === 'music' || rowMediaType === 'podcast')) {
      setStack(current => [...current, { screen: 'Music', params }]);
      return;
    }
    // Library is a tab, so stack callers such as Tags open the tab instead.
    if (screen === 'Library') { openTab('library', params?.mediaType); return; }
    setStack(current => [...current, { screen, params }]);
  };
  const openTab = (next, mediaType = libraryType) => {
    if (next === 'home') setTabHistory([]);
    else if (next !== tab || mediaType !== libraryType) {
      setTabHistory(current => [...current, { tab, libraryType, stack }]);
    }
    setStack([]);
    setLibraryType(mediaType);
    setTab(next);
  };
  const back = () => {
    if (stack.length) { setStack(current => current.slice(0, -1)); return; }
    const previous = tabHistory[tabHistory.length - 1];
    setTabHistory(current => current.slice(0, -1));
    setStack(previous?.stack || []);
    setTab(previous?.tab || 'home');
    if (previous) setLibraryType(previous.libraryType);
  };
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
  // model carries. Map them onto the native surfaces here, once. The server
  // may sit behind a base path (FORCE_SCRIPT_NAME deployments, and local
  // prefixed dev servers), so strip that prefix before matching routes.
  const openHref = (href, item) => {
    let path = String(href || '');
    try {
      const parsed = new URL(path, 'http://floppy.local');
      path = parsed.pathname;
    } catch {
      // Keep the raw string when it is not a URL.
    }
    const base = (() => {
      try { return new URL(session.serverUrl || '', 'http://floppy.local').pathname.replace(/\/+$/, ''); }
      catch { return ''; }
    })();
    if (base && base !== '/' && path.startsWith(`${base}/`)) path = path.slice(base.length);
    if (path === '/') { openTab('home'); return; }
    if (path === '/discover') { openTab('discover'); return; }
    if (path === '/calendar') { openTab('calendar'); return; }
    if (path.startsWith('/settings') || path === '/appearance') { openTab('settings'); return; }
    if (path === '/create') { navigate('Search', { createEntry: true }); return; }
    const media = path.match(/^\/medialist\/([^/?#]+)/);
    if (media) { openTab('library', media[1]); return; }
    if (path.startsWith('/collection')) { navigate('Collection'); return; }
    if (path.startsWith('/history')) { navigate('History'); return; }
    if (/^\/list\/[^/]+\/?$/.test(path) && item?.id) { navigate('ListDetail', { list: { id: item.id } }); return; }
    if (path.startsWith('/lists')) { navigate('Lists'); return; }
    if (path.startsWith('/statistics')) { navigate('Statistics'); return; }
    if (path.startsWith('/tags')) { navigate('Tags'); return; }
    // Music artist/album detail pages map onto the Music screen; the album
    // segment preselects the release. Other detail hrefs stay on Detail.
    const musicArtist = path.match(/^\/details\/music\/artist\/(\d+)/);
    if (musicArtist) {
      const musicAlbum = path.match(/\/album\/(\d+)/);
      navigate('Music', {
        artistId: Number(musicArtist[1]),
        ...(musicAlbum ? { albumId: Number(musicAlbum[1]) } : {}),
      });
      return;
    }
    const person = path.match(/^\/person\/([^/]+)\/([^/?#]+)/);
    if (person) { navigate('People', { identity: { kind: 'person', source: person[1], personId: person[2] } }); return; }
    const studio = path.match(/^\/studio\/([^/]+)\/([^/?#]+)/);
    if (studio) { navigate('People', { identity: { kind: 'studio', source: studio[1], studioId: studio[2] } }); return; }
    if (path.startsWith('/podcast/show/')) { navigate('Detail', { href: path }); return; }
    if (path.includes('/details/')) { navigate('Detail', { href: path }); }
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
    <ShellSlot standalone={active?.screen === 'Onboarding'} active={tab} activeHref={activeHref} canGoBack={Boolean(active) || tab !== 'home'} onBack={back} onNavigate={openTab} onOpenHref={openHref}
      onOpenSearch={params => navigate('Search', params)}
      onOpenSuggestion={item => navigate('Detail', { item })}>
      <View style={styles.body}>
        {active
          ? <ActiveScreen params={active.params} navigate={navigate} onBack={back} />
          : <ActiveScreen navigate={navigate} params={tabParams} onOpenTab={openTab} />}
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
