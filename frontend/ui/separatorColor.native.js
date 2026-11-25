import { Platform, PlatformColor } from 'react-native';

// iOS's `separator` system colour: it follows light and dark mode by itself.
export function systemSeparatorColor() {
  return Platform.OS === 'ios' ? PlatformColor('separator') : null;
}

// iOS's `tertiarySystemFill`: the neutral gray of Calendar's date and time chips, light and dark.
export function systemFillColor() {
  return Platform.OS === 'ios' ? PlatformColor('tertiarySystemFill') : null;
}
