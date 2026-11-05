import MusicScreen from './screens/MusicScreen';
import PeopleScreen from './screens/PeopleScreen';
import CollectionScreen from './screens/CollectionScreen';
import TagsScreen from './screens/TagsScreen';
import OnboardingScreen from './screens/OnboardingScreen';
import IntegrationsScreen from './screens/IntegrationsScreen';
import SettingsAdvancedScreen from './screens/SettingsAdvancedScreen';
import ErrorDocsScreen from './screens/ErrorDocsScreen';
import WebUtilitiesScreen from './screens/WebUtilitiesScreen';
import AuthScreen from './screens/AuthScreen';
import MetadataReviewScreen from './screens/MetadataReviewScreen';

// Temporary shell routes for screens that do not have a finished in-app
// navigation path yet. Each key is replaced by the real screen component as
// its surface is ported.
export const EXTRA_SCREENS = {
  Music: MusicScreen,
  People: PeopleScreen,
  Collection: CollectionScreen,
  Tags: TagsScreen,
  Onboarding: OnboardingScreen,
  Integrations: IntegrationsScreen,
  SettingsAdvanced: SettingsAdvancedScreen,
  ErrorDocs: ErrorDocsScreen,
  WebUtilities: WebUtilitiesScreen,
  Auth: AuthScreen,
  MetadataReview: MetadataReviewScreen,
};

export const EXTRA_LABELS = {
  Music: 'Music and podcasts',
  People: 'People, studios and credits',
  Collection: 'Collection and copies',
  Tags: 'Tags',
  Onboarding: 'Onboarding',
  Integrations: 'Library and request panels',
  SettingsAdvanced: 'Advanced and About',
  ErrorDocs: 'Errors and API docs',
  WebUtilities: 'Clipboard and install',
  Auth: 'Account and authentication',
  MetadataReview: 'Episode ordering, provider moves and remaps',
};
