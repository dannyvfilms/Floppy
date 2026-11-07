// Canonical page inventory for the web ↔ Expo parity migration.
//
// A page may claim `shared` only when its web adapter and native screen both
// import the same view module. `legacy` pages are honest gaps: the native
// screen still owns its own composition or the web page is server-owned.
export const pages = {
  home: {
    id: 'home',
    webRoute: '/',
    nativeScreen: 'native-proof/app/screens/HomeScreen.jsx',
    view: 'frontend/pages/HomeView.jsx',
    webAdapter: 'frontend/ui/mountHome.jsx',
    status: 'shared',
  },
  discover: { id: 'discover', webRoute: '/discover', nativeScreen: 'native-proof/app/screens/DiscoverScreen.jsx', status: 'legacy' },
  library: { id: 'library', webRoute: '/medialist/<type>', nativeScreen: 'native-proof/app/screens/LibraryScreen.jsx', view: 'frontend/pages/LibraryPageView.jsx', webAdapter: 'frontend/ui/mountLibraryPage.jsx', status: 'shared' },
  search: {
    id: 'search', webRoute: '/search',
    nativeScreen: 'native-proof/app/screens/SearchScreen.jsx',
    view: 'frontend/pages/SearchPageView.jsx',
    webAdapter: 'frontend/ui/mountSearchResults.jsx',
    status: 'shared',
  },
  detail: { id: 'detail', webRoute: '/details/<source>/<type>/<id>/<title>', nativeScreen: 'native-proof/app/screens/DetailScreen.jsx', view: 'frontend/pages/DetailView.jsx', webAdapter: 'frontend/ui/DetailCompositionTheme.web.jsx', status: 'shared' },
  people: { id: 'people', webRoute: '/people/...', nativeScreen: 'native-proof/app/screens/PeopleScreen.jsx', view: 'frontend/pages/PeopleView.jsx', webAdapter: 'frontend/ui/mountPeople.jsx', status: 'shared' },
  music: { id: 'music', webRoute: 'music/podcast detail routes', nativeScreen: 'native-proof/app/screens/MusicScreen.jsx', view: 'frontend/pages/MusicView.jsx', webAdapter: 'frontend/ui/mountMusicAlbums.jsx', status: 'shared' },
  collection: { id: 'collection', webRoute: '/collection', nativeScreen: 'native-proof/app/screens/CollectionScreen.jsx', view: 'frontend/pages/CollectionView.jsx', webAdapter: 'frontend/ui/mountCollectionBrowser.jsx', status: 'shared' },
  lists: { id: 'lists', webRoute: '/lists', nativeScreen: 'native-proof/app/screens/ListsScreen.jsx', view: 'frontend/pages/ListsPageView.jsx', webAdapter: 'frontend/ui/mountListsPage.jsx', status: 'shared' },
  listDetail: { id: 'listDetail', webRoute: '/lists/<id>', nativeScreen: 'native-proof/app/screens/ListDetailScreen.jsx', view: 'frontend/pages/ListDetailPageView.jsx', webAdapter: 'frontend/ui/mountListDetailPage.jsx', status: 'shared' },
  tags: {
    id: 'tags', webRoute: '/tags',
    nativeScreen: 'native-proof/app/screens/TagsScreen.jsx',
    view: 'frontend/pages/TagsPageView.jsx',
    webAdapter: 'frontend/ui/mountTags.jsx',
    status: 'shared',
  },
  history: { id: 'history', webRoute: '/history', nativeScreen: 'native-proof/app/screens/HistoryScreen.jsx', view: 'frontend/pages/HistoryView.jsx', webAdapter: 'frontend/ui/mountHistoryFeed.jsx', status: 'shared' },
  statistics: { id: 'statistics', webRoute: '/statistics', nativeScreen: 'native-proof/app/screens/StatisticsScreen.jsx', view: 'frontend/pages/StatisticsView.jsx', webAdapter: 'frontend/ui/mountStatisticsSummary.jsx', status: 'shared' },
  calendar: { id: 'calendar', webRoute: '/calendar', nativeScreen: 'native-proof/app/screens/CalendarScreen.jsx', view: 'frontend/pages/CalendarView.jsx', webAdapter: 'frontend/ui/mountReleaseCalendar.jsx', status: 'shared' },
  settings: { id: 'settings', webRoute: '/settings/...', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', view: 'frontend/pages/SettingsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAccount: { id: 'settingsAccount', webRoute: '/settings/account', nativeScreen: 'native-proof/app/screens/AuthScreen.jsx', view: 'frontend/pages/SettingsAccountView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsPreferences: { id: 'settingsPreferences', webRoute: '/settings/preferences', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/PreferencesSlot.jsx', view: 'frontend/pages/SettingsPreferencesView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsNotifications: { id: 'settingsNotifications', webRoute: '/settings/notifications', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/DataAccessNotificationsSlot.jsx', view: 'frontend/pages/SettingsNotificationsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAppearance: { id: 'settingsAppearance', webRoute: '/settings/appearance', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/AppearanceSettingsSlot.jsx', view: 'frontend/pages/SettingsAppearanceView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsCards: { id: 'settingsCards', webRoute: '/settings/cards', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/CardsSettingsSlot.jsx', view: 'frontend/pages/SettingsCardsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsHome: { id: 'settingsHome', webRoute: '/settings/home-screen', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/HomeSettingsSlot.jsx', view: 'frontend/pages/SettingsHomeScreenView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsData: { id: 'settingsData', webRoute: '/settings/data', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/DataAccessNotificationsSlot.jsx', view: 'frontend/pages/SettingsDataView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAccess: { id: 'settingsAccess', webRoute: '/settings/access', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/DataAccessNotificationsSlot.jsx', view: 'frontend/pages/SettingsAccessView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsUsers: { id: 'settingsUsers', webRoute: '/settings/users', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', nativeAdapter: 'native-proof/app/surfaces/UsersSlot.jsx', view: 'frontend/pages/SettingsUsersView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsSidebar: { id: 'settingsSidebar', webRoute: '/settings/sidebar', nativeScreen: 'native-proof/app/screens/SettingsScreen.jsx', view: null, status: 'legacy' },
  settingsAbout: { id: 'settingsAbout', webRoute: '/settings/about', nativeScreen: 'native-proof/app/screens/SettingsAdvancedScreen.jsx', view: 'frontend/pages/SettingsAboutView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAdvanced: { id: 'settingsAdvanced', webRoute: '/settings/advanced', nativeScreen: 'native-proof/app/screens/SettingsAdvancedScreen.jsx', view: 'frontend/pages/SettingsAdvancedView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  providers: { id: 'providers', webRoute: '/settings/providers...', nativeScreen: 'native-proof/app/screens/IntegrationsScreen.jsx', view: 'frontend/pages/ProvidersView.jsx', status: 'legacy' },
  auth: { id: 'auth', webRoute: '/accounts/...', nativeScreen: 'native-proof/app/screens/AuthScreen.jsx', view: 'frontend/pages/AuthView.jsx', status: 'legacy' },
  onboarding: { id: 'onboarding', webRoute: '/setup/...', nativeScreen: 'native-proof/app/screens/OnboardingScreen.jsx', view: 'frontend/pages/OnboardingView.jsx', status: 'legacy' },
  errors: { id: 'errors', webRoute: 'error routes, /api/docs/', nativeScreen: 'native-proof/app/screens/ErrorDocsScreen.jsx', view: 'frontend/pages/ErrorsView.jsx', webAdapter: 'frontend/errors/mountErrorRecovery.jsx', status: 'shared' },
  utilities: { id: 'utilities', webRoute: 'export/import/RSS/install/clipboard', nativeScreen: 'native-proof/app/screens/WebUtilitiesScreen.jsx', view: 'frontend/pages/UtilitiesView.jsx', status: 'legacy' },
};

export const sharedPages = Object.values(pages).filter(page => page.status === 'shared');
export const legacyPages = Object.values(pages).filter(page => page.status !== 'shared');
