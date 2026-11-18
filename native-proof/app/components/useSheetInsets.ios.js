import { useSafeAreaInsets } from 'react-native-safe-area-context';

// The sheet fills the rail background; leave room for its control without
// carrying the main app's full navigation gutter into the sheet body.
export function useSheetInsets() {
  const { left, right } = useSafeAreaInsets();
  return { left: Math.max(0, left - 24), right: Math.max(0, right - 24) };
}
