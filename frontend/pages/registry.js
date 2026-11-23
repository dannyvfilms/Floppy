// Canonical page inventory for the web ↔ Expo parity migration.
//
// A page may claim `shared` only when its web adapter and native screen both
// import the same view module. `legacy` pages are honest gaps: the native
// screen still owns its own composition or the web page is server-owned.
export const pages = {
  home: {
    id: 'home',
    webRoute: '/',
    nativeScreen: 'expo/app/screens/HomeScreen.jsx',
    view: 'frontend/pages/HomeView.jsx',
    webAdapter: 'frontend/ui/mountHome.jsx',
    status: 'shared',
  },
  discover: { id: 'discover', webRoute: '/discover', nativeScreen: 'expo/app/screens/DiscoverScreen.jsx', status: 'legacy' },
  library: { id: 'library', webRoute: '/medialist/<type>', nativeScreen: 'expo/app/screens/LibraryScreen.jsx', view: 'frontend/pages/LibraryPageView.jsx', webAdapter: 'frontend/ui/mountLibraryPage.jsx', status: 'shared' },
  search: {
    id: 'search', webRoute: '/search',
    nativeScreen: 'expo/app/screens/SearchScreen.jsx',
    view: 'frontend/pages/SearchPageView.jsx',
    webAdapter: 'frontend/ui/mountSearchResults.jsx',
    status: 'shared',
  },
  detail: { id: 'detail', webRoute: '/details/<source>/<type>/<id>/<title>', nativeScreen: 'expo/app/screens/DetailScreen.jsx', view: 'frontend/pages/DetailView.jsx', webAdapter: 'frontend/ui/DetailCompositionTheme.web.jsx', status: 'shared' },
  people: { id: 'people', webRoute: '/people/...', nativeScreen: 'expo/app/screens/PeopleScreen.jsx', view: 'frontend/pages/PeopleView.jsx', webAdapter: 'frontend/ui/mountPeople.jsx', status: 'shared' },
  music: { id: 'music', webRoute: 'music/podcast detail routes', nativeScreen: 'expo/app/screens/MusicScreen.jsx', view: 'frontend/pages/MusicView.jsx', webAdapter: 'frontend/ui/mountMusicAlbums.jsx', status: 'shared' },
  collection: { id: 'collection', webRoute: '/collection', nativeScreen: 'expo/app/screens/CollectionScreen.jsx', view: 'frontend/pages/CollectionView.jsx', webAdapter: 'frontend/ui/mountCollectionBrowser.jsx', status: 'shared' },
  lists: { id: 'lists', webRoute: '/lists', nativeScreen: 'expo/app/screens/ListsScreen.jsx', view: 'frontend/pages/ListsPageView.jsx', webAdapter: 'frontend/ui/mountListsPage.jsx', status: 'shared' },
  listDetail: { id: 'listDetail', webRoute: '/lists/<id>', nativeScreen: 'expo/app/screens/ListDetailScreen.jsx', view: 'frontend/pages/ListDetailPageView.jsx', webAdapter: 'frontend/ui/mountListDetailPage.jsx', status: 'shared' },
  tags: {
    id: 'tags', webRoute: '/tags',
    nativeScreen: 'expo/app/screens/TagsScreen.jsx',
    view: 'frontend/pages/TagsPageView.jsx',
    webAdapter: 'frontend/ui/mountTags.jsx',
    status: 'shared',
  },
  history: { id: 'history', webRoute: '/history', nativeScreen: 'expo/app/screens/HistoryScreen.jsx', view: 'frontend/pages/HistoryView.jsx', webAdapter: 'frontend/ui/mountHistoryFeed.jsx', status: 'shared' },
  progress: { id: 'progress', webRoute: '/progress', nativeScreen: 'expo/app/screens/ProgressScreen.jsx', view: 'frontend/pages/ProgressPageView.jsx', webAdapter: 'frontend/ui/mountProgressPage.jsx', status: 'shared' },
  statistics: { id: 'statistics', webRoute: '/statistics', nativeScreen: 'expo/app/screens/StatisticsScreen.jsx', view: 'frontend/pages/StatisticsView.jsx', webAdapter: 'frontend/ui/mountStatisticsSummary.jsx', status: 'shared' },
  calendar: { id: 'calendar', webRoute: '/calendar', nativeScreen: 'expo/app/screens/CalendarScreen.jsx', view: 'frontend/pages/CalendarView.jsx', webAdapter: 'frontend/ui/mountReleaseCalendar.jsx', status: 'shared' },
  settings: { id: 'settings', webRoute: '/settings/...', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', view: 'frontend/pages/SettingsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAccount: { id: 'settingsAccount', webRoute: '/settings/account', nativeScreen: 'expo/app/screens/AuthScreen.jsx', view: 'frontend/pages/SettingsAccountView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsPreferences: { id: 'settingsPreferences', webRoute: '/settings/preferences', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/PreferencesSlot.jsx', view: 'frontend/pages/SettingsPreferencesView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsNotifications: { id: 'settingsNotifications', webRoute: '/settings/notifications', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/NotificationsSettingsSlot.jsx', view: 'frontend/pages/SettingsNotificationsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAppearance: { id: 'settingsAppearance', webRoute: '/settings/appearance', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/AppearanceSettingsSlot.jsx', view: 'frontend/pages/SettingsAppearanceView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsCards: { id: 'settingsCards', webRoute: '/settings/cards', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/CardsSettingsSlot.jsx', view: 'frontend/pages/SettingsCardsView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsHome: { id: 'settingsHome', webRoute: '/settings/home-screen', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/HomeSettingsSlot.jsx', view: 'frontend/pages/SettingsHomeScreenView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsData: { id: 'settingsData', webRoute: '/settings/data', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/DataSettingsSlot.jsx', view: 'frontend/pages/SettingsDataView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAccess: { id: 'settingsAccess', webRoute: '/settings/access', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/AccessSettingsSlot.jsx', view: 'frontend/pages/SettingsAccessView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsUsers: { id: 'settingsUsers', webRoute: '/settings/users', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', nativeAdapter: 'expo/app/surfaces/UsersSlot.jsx', view: 'frontend/pages/SettingsUsersView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsSidebar: { id: 'settingsSidebar', webRoute: '/settings/sidebar', nativeScreen: 'expo/app/screens/SettingsScreen.jsx', view: null, status: 'legacy' },
  settingsAbout: { id: 'settingsAbout', webRoute: '/settings/about', nativeScreen: 'expo/app/screens/SettingsAdvancedScreen.jsx', nativeAdapter: 'expo/app/surfaces/AboutSettingsSlot.jsx', view: 'frontend/pages/SettingsAboutView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  settingsAdvanced: { id: 'settingsAdvanced', webRoute: '/settings/advanced', nativeScreen: 'expo/app/screens/SettingsAdvancedScreen.jsx', nativeAdapter: 'expo/app/surfaces/AdvancedSettingsSlot.jsx', view: 'frontend/pages/SettingsAdvancedView.jsx', webAdapter: 'frontend/settings/mountSettingsView.jsx', status: 'shared' },
  providers: { id: 'providers', webRoute: '/settings/providers...', nativeScreen: 'expo/app/screens/ProvidersScreen.jsx', view: 'frontend/pages/ProvidersView.jsx', status: 'legacy' },
  auth: { id: 'auth', webRoute: '/accounts/...', nativeScreen: 'expo/app/screens/AuthScreen.jsx', view: 'frontend/pages/AuthView.jsx', status: 'legacy' },
  onboarding: { id: 'onboarding', webRoute: '/setup/...', nativeScreen: 'expo/app/screens/OnboardingScreen.jsx', view: 'frontend/pages/OnboardingView.jsx', status: 'legacy' },
  errors: { id: 'errors', webRoute: 'error routes, /api/docs/', nativeScreen: 'expo/app/screens/ErrorDocsScreen.jsx', view: 'frontend/pages/ErrorsView.jsx', webAdapter: 'frontend/errors/mountErrorRecovery.jsx', status: 'shared' },
  providerDetail: { id: 'providerDetail', webRoute: '/settings/providers/<slug>', nativeScreen: 'expo/app/screens/ProviderDetailScreen.jsx', view: 'frontend/pages/ProviderDetailView.jsx', status: 'legacy' },
  connections: { id: 'connections', webRoute: 'sync connections, conflicts and device approval', nativeScreen: 'expo/app/screens/ConnectionsScreen.jsx', view: 'frontend/pages/ConnectionsView.jsx', status: 'legacy' },
  metadataReview: { id: 'metadataReview', webRoute: 'metadata review queue', nativeScreen: 'expo/app/screens/MetadataReviewScreen.jsx', view: 'frontend/pages/MetadataReviewView.jsx', status: 'legacy' },
  utilities: { id: 'utilities', webRoute: 'export/import/RSS/install/clipboard', nativeScreen: 'expo/app/screens/UtilitiesScreen.jsx', view: 'frontend/pages/UtilitiesView.jsx', status: 'legacy' },
};

export const sharedPages = Object.values(pages).filter(page => page.status === 'shared');
export const legacyPages = Object.values(pages).filter(page => page.status !== 'shared');
