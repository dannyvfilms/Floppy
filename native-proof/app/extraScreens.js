import MusicScreen from './screens/MusicScreen';
import PeopleScreen from './screens/PeopleScreen';
import CollectionScreen from './screens/CollectionScreen';
import TagsScreen from './screens/TagsScreen';
import SettingsAdvancedScreen from './screens/SettingsAdvancedScreen';
import AuthScreen from './screens/AuthScreen';
import ErrorDocsScreen from './screens/ErrorDocsScreen';
import ProvidersScreen from './screens/ProvidersScreen';
import ProviderDetailScreen from './screens/ProviderDetailScreen';
import ConnectionsScreen from './screens/ConnectionsScreen';
import MetadataReviewScreen from './screens/MetadataReviewScreen';
import UtilitiesScreen from './screens/UtilitiesScreen';
import OnboardingScreen from './screens/OnboardingScreen';

// Stack routes for ported screens that render from the drawer but are not
// top-level tabs. Entries appear here as their surfaces reach real data.
export const EXTRA_SCREENS = {
  Music: MusicScreen,
  People: PeopleScreen,
  Collection: CollectionScreen,
  Tags: TagsScreen,
  SettingsAdvanced: SettingsAdvancedScreen,
  Auth: AuthScreen,
  ErrorDocs: ErrorDocsScreen,
  Providers: ProvidersScreen,
  ProviderDetail: ProviderDetailScreen,
  Connections: ConnectionsScreen,
  MetadataReview: MetadataReviewScreen,
  Utilities: UtilitiesScreen,
  Onboarding: OnboardingScreen,
};
